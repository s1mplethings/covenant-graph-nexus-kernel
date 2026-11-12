"""Portable candidates use FileRunStore; import never grants PASS or execution."""
import hashlib
import json
from pathlib import Path
from veriarbor.block import Block
from veriarbor.component_package import pack, unpack
from cgkn.execution.file_actions import BoundedFileActions


class ComponentPackages:
    def __init__(self, store, project_id, run_id):
        self.store,self.project_id,self.run_id=store,project_id,run_id
        self.root=store.run_dir(project_id,run_id)/'component_packages'

    def export(self, *, block, artifact_paths, receipt_id, authority, entrypoint, dependencies, applicability, invocation=None):
        receipt=authority.validate_receipt(receipt_id,capability_id=block.capability)
        if set(artifact_paths)!=dict(block.variant.artifacts).keys():raise ValueError('exact artifact mapping required')
        contents={}
        for name,source in artifact_paths.items():
            path=Path(source).resolve();raw=path.read_bytes();digest=hashlib.sha256(raw).hexdigest()
            authority.validate_receipt(receipt_id,output_path=str(path),output_hash=digest)
            contents[name]=raw
        value=pack(block,contents,entrypoint=entrypoint,dependencies=dependencies,applicability=applicability,invocation=invocation)
        self.store.immutable_json(self.root/(value['identity']+'.json'),value)
        return value

    def import_candidate(self, value, *, context, dependencies):
        for name,identity in dependencies.items():
            if self.resolve(identity,context)[identity][1].block_id!=name:
                raise ValueError('dependency block identity mismatch')
        block,contents=unpack(value,available=dependencies,context=context)
        self.store.immutable_json(self.root/(value['identity']+'.json'),value)
        destination=self.root/value['identity']/'files'
        for name,raw in contents.items():
            path=BoundedFileActions(destination)._path(name)
            path.parent.mkdir(parents=True,exist_ok=True)
            if path.exists():
                if path.read_bytes()!=raw:raise ValueError('immutable imported artifact changed')
            else:
                with path.open('xb') as handle:handle.write(raw)
        return {'identity':value['identity'],'block':block.as_dict(),'entrypoint':value['entrypoint'],
                'input_paths':{name:str(destination/name) for name in contents},
                'dependency_identities':dependencies,'qualification':'NEEDS_REVALIDATION',
                'execution':'Agent must propose current-context nodes through normal admission'}

    def resolve(self, identity, context, *, visiting=None):
        if not isinstance(identity,str) or len(identity)!=64 or any(c not in '0123456789abcdef' for c in identity):
            raise ValueError('invalid package identity')
        visiting=set() if visiting is None else set(visiting)
        if identity in visiting:raise ValueError('cyclic package dependency')
        if len(visiting)>=32:raise ValueError('package dependency depth exceeded')
        visiting.add(identity)
        path=BoundedFileActions(self.root)._path(identity+'.json')
        if path.stat().st_size>12_000_000:raise ValueError('package envelope exceeds bound')
        value=json.loads(path.read_text(encoding='utf-8'))
        block,contents=unpack(value,available=value['dependencies'],context=context)
        if value['identity']!=identity:raise ValueError('package identity changed')
        closure={identity:(value,block,contents)}
        for name,child in value['dependencies'].items():
            resolved=self.resolve(child,context,visiting=visiting)
            if resolved[child][1].block_id!=name:raise ValueError('dependency block identity mismatch')
            closure.update(resolved)
            if len(closure)>32:raise ValueError('package dependency count exceeded')
        return closure

    def catalog(self, context):
        rows=[]
        for path in sorted(self.root.glob('*.json')):
            try:
                closure=self.resolve(path.stem,context)
                value,block,contents=closure[path.stem]
            except (ValueError,OSError,KeyError):continue
            rows.append({'identity':value['identity'],'block':block.as_dict(),
                'entrypoint':value['entrypoint'],'read_paths':['inputs/components/'+value['identity']+'/'+n for n in contents],
                'qualification':'NEEDS_REVALIDATION','dependencies':value['dependencies'],
                'invocation':value.get('invocation'),
                'executor_ref':'local.component@1' if value.get('invocation') else None})
        return rows

    def materialize_inputs(self, workspace, context):
        for row in self.catalog(context):
            value=json.loads((self.root/(row['identity']+'.json')).read_text(encoding='utf-8'))
            _,contents=unpack(value,available=value['dependencies'],context=context)
            for name,raw in contents.items():
                path=BoundedFileActions(workspace)._path('inputs/components/'+row['identity']+'/'+name)
                path.parent.mkdir(parents=True,exist_ok=True)
                if path.exists():
                    if path.read_bytes()!=raw:raise ValueError('imported input identity changed')
                else:
                    with path.open('xb') as handle:handle.write(raw)


def validate_ports(ports, values):
    from jsonschema import Draft202012Validator
    if not isinstance(values,dict) or set(values)-{p.port_id for p in ports}:
        raise ValueError('undeclared component ports')
    result=dict(values)
    for port in ports:
        if port.evidence_policy:
            raise ValueError('this stdio adapter requires an explicit adapter for evidence-bearing ports')
        if port.port_id not in result:
            if port.required:raise ValueError('missing required port: '+port.port_id)
            result[port.port_id]=json.loads(port.default_json)
        Draft202012Validator.check_schema(port.contract.schema)
        Draft202012Validator(port.contract.schema).validate(result[port.port_id])
    return result


class PortableComponentExecutor:
    """Thin data adapter: DAGRunner owns staging, effects, commit and acceptance."""
    from cgkn.execution.contracts import ExecutorDescriptor
    descriptor=ExecutorDescriptor('local.component@1','portable_component',('*',),
        ('filesystem.read','filesystem.write','process.execute'))

    def __init__(self, root, packages, context):
        self.candidate_root=Path(root).resolve()
        self.packages=packages
        self.context=dict(context)
        self.resource_claims={'workspace:'+str(self.candidate_root):'write'}

    def in_candidate_workspace(self, directory):
        from copy import copy
        worker=copy(self);worker.candidate_root=Path(directory).resolve()
        return worker

    def compile(self, cfg, node, dependencies, workspace):
        from cgkn.orchestration.leaf_contract import build_leaf_contract
        from dataclasses import asdict
        closure=self.packages.resolve(cfg['package_identity'],self.context)
        packet,block,_=closure[cfg['package_identity']]
        if packet.get('invocation',{}).get('protocol')!='python-json-stdio@1':
            raise ValueError('source-only package has no declared executable adapter')
        if set(block.effect_contract.external_effects)-{'local_process'}:
            raise ValueError('portable adapter does not grant remote or undeclared host effects')
        outputs=cfg.get('output_paths',{})
        if set(outputs)!={p.port_id for p in block.output_ports}:
            raise ValueError('every declared output port requires an explicit destination')
        paths=list(outputs.values())
        from cgkn.application.goal_driven import relative_files
        relative_files(paths)
        if len(set(paths))!=len(paths) or not paths:raise ValueError('distinct output destinations required')
        reads={}
        for identity,(_,_,contents) in closure.items():
            for name,raw in contents.items():
                relative='inputs/components/'+identity+'/'+name
                source=BoundedFileActions(workspace)._path(relative)
                digest=hashlib.sha256(raw).hexdigest()
                if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest()!=digest:
                    raise ValueError('imported implementation input missing or changed')
                reads[relative]=digest
        literals=cfg.get('inputs',{});bindings=cfg.get('bindings',{})
        if set(literals)&set(bindings):raise ValueError('duplicate input binding')
        declared={p.port_id for p in block.input_ports}
        if (set(literals)|set(bindings))-declared:raise ValueError('unknown input port')
        for port,binding in bindings.items():
            if set(binding)!={'node_id','port_id'} or binding['node_id'] not in dependencies:
                raise ValueError('component binding must name an admitted dependency node and output port')
        if not bindings:validate_ports(block.input_ports,literals)
        cfg={**cfg,'portable_boundary_hashes':list(block.boundary_hashes),
             'input_paths':[str(Path(workspace)/name) for name in reads]}
        leaf=build_leaf_contract(goal=cfg['goal'],kind='IMPLEMENTATION',scope=paths,
            acceptance=['local-artifacts'],checker='files',output_identity=node,
            effect_domains=['filesystem','local_process'],executor=self.descriptor.executor_ref,
            dependencies=dependencies,expected_delta='Produce declared component output ports',
            read_scope=list(reads),read_subjects=reads,atomic_component=True,
            portable_output_contracts={outputs[p.port_id]:asdict(p) for p in block.output_ports})
        return cfg,leaf

    def execute(self, request):
        from dataclasses import replace
        from cgkn.execution import BlockStatus,ExecutionError,ExecutionErrorCode
        from cgkn.executors.local import CommandExecutor
        from cgkn.execution.node_effects import guard_effect
        import sys
        from jsonschema.exceptions import ValidationError,SchemaError
        cfg=request.task_context.as_dict()['node_config']
        from cgkn.execution import BlockExecutionResult
        def failure(message, *, unknown=False, observed=None):
            return BlockExecutionResult(project_id=request.project_id,run_id=request.run_id,
                attempt_id=request.attempt_id,node_id=request.node_id,executor_ref=request.executor_ref,
                status=BlockStatus.BLOCKED if unknown else BlockStatus.FAILED,
                outputs={'process_observation':observed or {}},
                error=ExecutionError(ExecutionErrorCode.CONTRACT_ERROR,message,{'outcome_unknown':unknown}),retryable=False)
        try:
            closure=self.packages.resolve(cfg['package_identity'],self.context)
            packet,block,_=closure[cfg['package_identity']]
            if (packet.get('invocation',{}).get('protocol')!='python-json-stdio@1' or
                    set(block.effect_contract.external_effects)-{'local_process'}):
                raise ValueError('unsupported component invocation or effects')
            if list(block.boundary_hashes)!=list(cfg['portable_boundary_hashes']):
                raise ValueError('component boundary identity changed; explicit adapter or new admission required')
            for name,digest in cfg['leaf_contract']['read_subjects'].items():
                raw=BoundedFileActions(self.candidate_root)._path(name).read_bytes()
                if hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('candidate implementation identity changed')
            values=request.as_dict()['input_values']
            for port,binding in cfg.get('bindings',{}).items():
                producer=request.task_context.as_dict()['dependency_results'][binding['node_id']]
                values[port]=producer['ports'][binding['port_id']]
            values=validate_ports(block.input_ports,values)
            entry=BoundedFileActions(self.candidate_root)._path('inputs/components/'+packet['identity']+'/'+packet['entrypoint'])
            payload={'inputs':values,'dependencies':{name:{'root':'inputs/components/'+identity,
                'entrypoint':closure[identity][0]['entrypoint']} for name,identity in packet['dependencies'].items()}}
            context=replace(request.task_context,node_config={'command':[sys.executable,'-E','-s','-X','utf8',str(entry)],
                'cwd':'.','stdin_text':json.dumps(payload,ensure_ascii=False),'text_encoding':'utf-8'})
            result=CommandExecutor(self.candidate_root).execute(replace(request,task_context=context))
            if result.status is BlockStatus.TIMED_OUT:
                return failure('component subprocess requires outcome reconciliation',unknown=True,observed=result.as_dict())
            if not result.succeeded:return replace(result,retryable=False)
            for name,digest in cfg['leaf_contract']['read_subjects'].items():
                if hashlib.sha256(BoundedFileActions(self.candidate_root)._path(name).read_bytes()).hexdigest()!=digest:
                    raise ValueError('component mutated immutable input')
            ports=validate_ports(block.output_ports,json.loads(result.outputs['stdout']))
            guard_effect(request,'PERSISTENT_ARTIFACT_WRITE')
            for port,name in cfg['output_paths'].items():
                path=BoundedFileActions(self.candidate_root)._path(name)
                path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text(json.dumps(ports[port],ensure_ascii=False,sort_keys=True),encoding='utf-8')
            return replace(result,outputs={'ports':ports,'package_identity':packet['identity'],
                'boundary_hashes':list(block.boundary_hashes),'process_observation':result.as_dict()['outputs']},
                metadata={**result.metadata,'qualification':'INDEPENDENT_ACCEPTANCE_REQUIRED'})
        except (ValueError,OSError,KeyError,TypeError,ValidationError,SchemaError) as exc:
            return failure(str(exc))
