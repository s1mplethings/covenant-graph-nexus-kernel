"""Closed public declarations projected into existing immutable run contracts."""
import copy
from .normalization import ContractError,digest

SECTIONS=('interface','fields','types','exceptions','idempotency','persistence','ordering','concurrency','edge_behavior')


def _strings(value):
    return isinstance(value,list) and bool(value) and all(isinstance(v,str) and v.strip() for v in value)


def _field_structure(value):
    """Legacy string leaves or explicit typed leaves, never ignored content."""
    if not isinstance(value,dict) or not value:return False
    for name,leaf in value.items():
        if not isinstance(name,str) or not name.strip():return False
        if isinstance(leaf,str):
            if not leaf.strip():return False
        elif isinstance(leaf,dict) and 'type' in leaf:
            if not isinstance(leaf['type'],str) or not leaf['type'].strip():return False
            if set(leaf)-{'type','required','consumers','description'}:return False
            if 'required' in leaf and type(leaf['required']) is not bool:return False
            if 'consumers' in leaf and not _strings(leaf['consumers']):return False
        elif not _field_structure(leaf):return False
    return True

def field_rows(fields,parent=()):
    if not isinstance(fields,dict):return []
    rows=[]
    for name,value in fields.items():
        if isinstance(value,str):rows.append({'name':name,'type':value,'owner':'/'.join(parent) or '$contract'})
        elif isinstance(value,dict) and 'type' in value:rows.append({'name':name,'type':value['type'],'owner':'/'.join(parent) or '$contract'})
        elif isinstance(value,dict):rows+=field_rows(value,parent+(name,))
    return rows

class ContractIntegrityChecker:
    @staticmethod
    def declared_exports(entry):
        rows=[];errors=[]
        for artifact in entry.get('artifact_declarations',[]):
            if not isinstance(artifact,dict) or not isinstance(artifact.get('path'),str):
                errors.append({'code':'CONTRACT_EXPORT_AMBIGUOUS','reason':'artifact path required'});continue
            interface=artifact.get('interfaces',{})
            if not isinstance(interface,dict) or 'public_exports' not in interface:
                errors.append({'code':'CONTRACT_EXPORT_AMBIGUOUS','artifact':artifact.get('path'),'reason':'Declare public_exports explicitly (empty list for private-only artifacts); do not infer visibility from symbol names.'});continue
            if not isinstance(interface['public_exports'],list):
                errors.append({'code':'CONTRACT_EXPORT_AMBIGUOUS','artifact':artifact.get('path')});continue
            for export in interface['public_exports']:
                if not isinstance(export,dict) or not all(export.get(k) for k in ('name','kind')) or export['kind'] not in {'function','class','exception','constant'}:
                    errors.append({'code':'CONTRACT_EXPORT_AMBIGUOUS','artifact':artifact.get('path'),'declaration':export});continue
                rows.append({'name':export['name'],'kind':export['kind'],'owner':artifact['path'],
                    'source_ref':entry.get('source_decision'),'source_declaration_hash':digest(artifact)})
        return rows,errors

    @classmethod
    def project_exports(cls,document):
        result=copy.deepcopy(document);receipts=[]
        for entry in result.get('entries',[]):
            declared,errors=cls.declared_exports(entry)
            if errors:raise ContractError('CONTRACT_EXPORT_AMBIGUOUS',details={'errors':errors})
            exports=entry['definition'].setdefault('exports',[])
            if not isinstance(exports,list):raise ContractError('CONTRACT_EXPORT_AMBIGUOUS')
            for row in declared:
                existing=[x for x in exports if isinstance(x,dict) and x.get('name')==row['name'] and x.get('owner')==row['owner']]
                if existing and any(x.get('kind')!=row['kind'] for x in existing):
                    raise ContractError('CONTRACT_EXPORT_CONTRADICTION',details={'declared':row,'registry':existing})
                if not existing:
                    exports.append(copy.deepcopy(row));receipts.append({'rule':'copy explicit public export name/kind/owner; infer no signature, inheritance or exception policy',
                        'source_declaration':row,'before':None,'after':row,'semantics_changed':False})
        return result,receipts

    @classmethod
    def audit(cls,document,*,leaf=None):
        issues=[];checked=[]
        entries=document.get('entries',[])
        if not isinstance(entries,list):entries=[]
        if not entries:issues.append({'code':'CONTRACT_REGISTRY_EMPTY'})
        for entry in entries:
            if not isinstance(entry,dict):issues.append({'code':'CONTRACT_ENTRY_INVALID'});continue
            ident=entry.get('contract_id');definition=entry.get('definition',{})
            if not isinstance(definition,dict):issues.append({'code':'CONTRACT_SECTION_INCOMPLETE','contract_id':ident});continue
            missing=[s for s in SECTIONS if not definition.get(s)]
            if missing:issues.append({'code':'CONTRACT_SECTION_INCOMPLETE','contract_id':ident,'missing':missing})
            if entry.get('integrity_version')!=2 or not entry.get('artifact_declarations'):
                issues.append({'code':'CONTRACT_INTEGRITY_UNDECLARED','contract_id':ident})
            declared,errors=cls.declared_exports(entry);issues+=errors
            exports=definition.get('exports',[])
            if not isinstance(exports,list):exports=[];issues.append({'code':'CONTRACT_EXPORT_INCOMPLETE','contract_id':ident})
            for row in declared:
                matches=[x for x in exports if isinstance(x,dict) and all(x.get(k)==row[k] for k in ('name','owner','kind'))]
                if not matches:issues.append({'code':'CONTRACT_EXPORT_INCOMPLETE','contract_id':ident,'missing_export':row})
            for export in exports:
                if not isinstance(export,dict) or not any(all(export.get(k)==row[k] for k in ('name','owner','kind')) for row in declared):
                    issues.append({'code':'CONTRACT_EXPORT_CONTRADICTION','contract_id':ident,'export':export})
            fields=definition.get('field_contracts',[])
            if not isinstance(fields,list):fields=[]
            if not _field_structure(definition.get('fields')):
                issues.append({'code':'CONTRACT_FIELD_SCHEMA_INVALID','contract_id':ident})
            expected=field_rows(definition.get('fields'))
            for row in expected:
                matches=[x for x in fields if isinstance(x,dict) and all(x.get(k)==row[k] for k in ('name','type','owner'))]
                if not matches or any(type(x.get('required')) is not bool or not _strings(x.get('consumers')) for x in matches):
                    issues.append({'code':'CONTRACT_FIELD_INCOMPLETE','contract_id':ident,'field':row})
            for row in fields:
                if not isinstance(row,dict) or {k:row.get(k) for k in ('name','type','owner')} not in expected:
                    issues.append({'code':'CONTRACT_FIELD_CONTRADICTION','contract_id':ident,'field':row})
            shapes=definition.get('return_shapes',{})
            expected_shapes={row['owner']:sorted(x['name'] for x in expected if x['owner']==row['owner']) for row in expected}
            valid_shapes=isinstance(shapes,dict) and all(isinstance(k,str) and isinstance(v,list) and all(isinstance(x,str) for x in v) for k,v in shapes.items())
            if not valid_shapes or {k:sorted(v) for k,v in shapes.items()}!=expected_shapes:
                issues.append({'code':'CONTRACT_RETURN_SHAPE_INCOMPLETE','contract_id':ident,'expected':expected_shapes})
            exceptions=definition.get('exceptions',{})
            bindings=definition.get('exception_bindings',[])
            if not isinstance(bindings,list):bindings=[]
            for export in exports:
                if not isinstance(export,dict) or export.get('kind')!='exception':continue
                name=export['name'];policy=exceptions.get(name) if isinstance(exceptions,dict) else None
                matches=[x for x in bindings if isinstance(x,dict) and x.get('name')==name]
                if not policy or not matches or any(x.get('policy')!=policy or not all(x.get(k) for k in ('implementation_ref','test_refs','acceptance_refs')) for x in matches):
                    issues.append({'code':'CONTRACT_EXCEPTION_INCOMPLETE','contract_id':ident,'exception':name})
            acceptance=definition.get('acceptance_bindings',[])
            if not isinstance(acceptance,list):acceptance=[]
            if not acceptance:issues.append({'code':'CONTRACT_ACCEPTANCE_INCOMPLETE','contract_id':ident})
            for row in acceptance:
                if not isinstance(row,dict) or not all(row.get(k) for k in ('acceptance_id','contract_id','checker_ref','object_ref','version')) or row.get('contract_id')!=ident:
                    issues.append({'code':'CONTRACT_ACCEPTANCE_INCOMPLETE','contract_id':ident,'binding':row})
            for must in entry.get('must_acceptance_ids',[]):
                if not any(isinstance(x,dict) and x.get('acceptance_id')==must for x in acceptance):issues.append({'code':'CONTRACT_ACCEPTANCE_INCOMPLETE','contract_id':ident,'missing_must':must})
            if leaf and not set(leaf.get('target_scope',[])).intersection(entry.get('artifact_paths',[])):
                issues.append({'code':'CONTRACT_OBJECT_UNBOUND','contract_id':ident})
            checked.append({'contract_id':ident,'exports':len(declared),'fields':len(expected),'acceptance_bindings':len(acceptance)})
        return {'kind':'ContractIntegrityReceipt','status':'PASS' if not issues else 'FAIL','registry_hash':document.get('registry_hash',digest(document)),'selected_contracts_hash':digest(document),
            'checked':checked,'issues':issues,'scope':'declared public contract closure; does not assert implementation correctness'}

    @classmethod
    def require(cls,document,*,leaf=None):
        receipt=cls.audit(document,leaf=leaf)
        if receipt['status']!='PASS':
            raise ContractError(receipt['issues'][0]['code'],details={'failure_domain':'CONTRACT','integrity_receipt':receipt,'provider_dispatched':False,'correction_path_terminated':True})
        return receipt
