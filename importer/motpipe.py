"""Explicit, source-verified MOT pipe-envelope dialect (not RFC4180).
Unquoted header; quoted populated cells; bare empty cells; internal quotes literal.
A field ends only at quote+pipe or the final record quote. This preserves pipes
inside quoted cells. Dialect must be verified per source, never auto-fallback.
"""
PARSER_VERSION='mot-envelope-2'

def _record(body,expected):
    values=[];position=0
    while True:
        if position==len(body):
            values.append('');break
        if body[position]=='|':
            values.append('');position+=1
        elif body[position]=='"':
            end=body.find('"|',position+1)
            if end>=0:
                values.append(body[position+1:end]);position=end+2
            elif len(body)>position+1 and body.endswith('"'):
                values.append(body[position+1:-1]);break
            else:
                return None  # bounded continuation within an open envelope
        else:
            raise ValueError('MOT field lacks quote envelope')
        if len(values)>expected:
            raise ValueError('MOT record has excess envelope delimiters')
    if len(values)!=expected:
        raise ValueError('MOT record width differs from header')
    return values

def rows(stream,max_record_chars=1024*1024):
    line=stream.readline()
    if not line:raise ValueError('missing MOT header')
    header=line.rstrip('\r\n').split('|')
    if any(not name or '"' in name for name in header) or len(set(header))!=len(header):
        raise ValueError('invalid MOT header')
    yield header
    pending=''
    for line in stream:
        pending+=line
        if len(pending)>max_record_chars:raise ValueError('MOT record exceeds bounded size')
        record=_record(pending.rstrip('\r\n'),len(header))
        if record is not None:
            yield record;pending=''
    if pending:raise ValueError('unterminated MOT envelope record')
