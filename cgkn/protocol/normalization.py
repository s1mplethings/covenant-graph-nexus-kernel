"""Safe lexical/type normalization, with no business inference."""
from __future__ import annotations
import hashlib,json,re,math

MAX_BYTES=262144
VECTOR_KEYS=('syntax_errors','coercible_type_errors','known_alias_errors','missing_mechanical_fields','invalid_registry_ids','missing_semantic_fields','semantic_contradictions','unknown_errors')

def digest(value):
    raw=value if isinstance(value,bytes) else json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()

class ContractError(ValueError):
    def __init__(self,code,*,fields=(),repair_class='R7',vector_key='unknown_errors',details=None):
        super().__init__(code)
        self.code=code;self.fields=tuple(fields);self.repair_class=repair_class
        self.vector={k:int(k==vector_key) for k in VECTOR_KEYS}
        self.details=dict(details or {})
    def as_dict(self):return {**self.details,'code':self.code,'fields':list(self.fields),'repair_class':self.repair_class,'error_vector':self.vector}

def _object(pairs):
    result={}
    for k,v in pairs:
        if k in result:raise ContractError('DUPLICATE_KEY',fields=(k,))
        result[k]=v
    return result


def _finite_float(text):
    value=float(text)
    if not math.isfinite(value):raise ContractError('NONFINITE_NUMBER')
    return value

def _trailing_commas(text):
    out=[];inside=False;escape=False;changed=False
    for i,ch in enumerate(text):
        if inside:
            out.append(ch)
            if escape:escape=False
            elif ch=='\\':escape=True
            elif ch=='"':inside=False
            continue
        if ch=='"':inside=True
        if ch==',':
            tail=i+1
            while tail<len(text) and text[tail].isspace():tail+=1
            if tail<len(text) and text[tail] in '}]':
                previous=''.join(out).rstrip()
                if not previous or previous[-1] in '[{,:':raise ContractError('AMBIGUOUS_TRAILING_COMMA')
                changed=True;continue
        out.append(ch)
    return ''.join(out),changed

def normalize(text,*,integer_fields=(),list_fields=(),aliases=None):
    if not isinstance(text,str) or len(text.encode())>MAX_BYTES:raise ContractError('OVERSIZED_OR_NON_TEXT')
    before=digest(text.encode());rules=[];clean=text.strip()
    if clean.startswith('```'):
        lines=clean.splitlines()
        if len(lines)<3 or lines[-1].strip()!='```' or lines[0].strip() not in {'```','```json'}:raise ContractError('AMBIGUOUS_FENCE')
        clean='\n'.join(lines[1:-1]);rules.append('REMOVE_JSON_FENCE')
    clean,changed=_trailing_commas(clean)
    if changed:rules.append('REMOVE_TRAILING_COMMA_OUTSIDE_STRINGS')
    try:value=json.loads(clean,object_pairs_hook=_object,parse_float=_finite_float,parse_constant=lambda x:(_ for _ in ()).throw(ContractError('NONFINITE_NUMBER')))
    except json.JSONDecodeError as exc:raise ContractError('INVALID_OR_INCOMPLETE_JSON',vector_key='syntax_errors') from exc
    except RecursionError as exc:raise ContractError('JSON_PARSER_RESOURCE_LIMIT',details={'failure_domain':'RESOURCE_LIMIT'}) from exc
    if not isinstance(value,dict):raise ContractError('OBJECT_REQUIRED')
    aliases=aliases or {}
    for alias,key in aliases.items():
        if alias in value:
            if key in value:raise ContractError('AMBIGUOUS_ALIAS',fields=(alias,key))
            value[key]=value.pop(alias);rules.append('ALIAS:'+alias+'->'+key)
    for key in integer_fields:
        v=value.get(key)
        if isinstance(v,str) and re.fullmatch(r'0|[1-9][0-9]*',v):value[key]=int(v);rules.append('INTEGER_STRING:'+key)
    for key in list_fields:
        if key not in value:continue
        v=value[key]
        if type(v) is int:v=[v];rules.append('SINGLETON_ID:'+key)
        if isinstance(v,list):
            converted=[]
            for item in v:
                if isinstance(item,str) and re.fullmatch(r'0|[1-9][0-9]*',item):item=int(item);rules.append('INTEGER_STRING:'+key)
                converted.append(item)
            # Only declared ID sets can be sorted/deduplicated; never code/text lists.
            if all(type(x) is int for x in converted):
                unique=sorted(set(converted))
                if unique!=converted:rules.append('CANONICAL_ID_SET:'+key)
                v=unique
            else:v=converted
        value[key]=v
    classes=['R3' if r.startswith('ALIAS:') else 'R2' if r.startswith(('INTEGER_STRING:','SINGLETON_ID:','CANONICAL_ID_SET:')) else 'R1' for r in rules]
    return value,{'before_hash':before,'after_hash':digest(value),'applied_rules':rules,'semantics_changed':False,'repair_class':max(classes,default='R0')}

def preserve_valid_fields(before,after,invalid_fields):
    changed=[k for k in set(before)|set(after) if before.get(k)!=after.get(k) or (k in before)!=(k in after)]
    forbidden=set(changed)-set(invalid_fields)
    if forbidden:raise ContractError('CORRECTION_CHANGED_IMMUTABLE_FIELDS',fields=sorted(forbidden),repair_class='R6',vector_key='semantic_contradictions')
    return {'before_hash':digest(before),'after_hash':digest(after),'changed_fields':sorted(changed),'unrelated_fields_changed':0}
