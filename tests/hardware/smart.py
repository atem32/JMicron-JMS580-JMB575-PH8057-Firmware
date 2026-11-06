"""Parse ATA smartctl snapshots without treating missing data as zero.

Supports the standard -A and extended -x text tables, plus smartctl JSON.
Attribute IDs are the comparison keys: vendor names may vary between releases.
"""
import json
import re

REQUIRED_IDS = frozenset(('5', '197', '198', '199'))
CONCERNING_IDS = REQUIRED_IDS | frozenset(('187', '188'))


def _raw_integer(raw):
    # Numeric prefix is the count; retain units/vendor annotations separately.
    # Hex values are supported explicitly, never interpreted as decimal zero.
    match = re.match(r'^\s*(0x[0-9a-fA-F]+|[0-9]+)(?=\s|$|\()', str(raw))
    if not match:
        return None
    value = match.group(1)
    return int(value, 16 if value.lower().startswith('0x') else 10)


def parse_smart(text, exit_code=None):
    """Return identity, all ATA attributes and acquisition/parse diagnostics.

    exit_code is smartctl's bit mask, not a conventional zero/nonzero result.
    Bits 0..2 indicate command/acquisition errors. Health bits 3..4 describe
    current health failures; the log/self-test bits are retained separately.
    """
    result = {'serial': None, 'model': None, 'attributes': {},
              'exit_code': exit_code, 'errors': [], 'acquisition_errors': [],
              'health_alert': False}
    # The recorder's process status takes precedence over smartctl's embedded
    # JSON status. A process can be killed or fail after it writes valid JSON.
    wrapped_codes = [int(value) for value in
                     re.findall(r'^Exit code:\s*(-?\d+)\s*$', text, re.M)]
    if wrapped_codes:
        if exit_code is None:
            result['exit_code'] = wrapped_codes[0]
        if any(value != result['exit_code'] for value in wrapped_codes):
            result['acquisition_errors'].append('exit_status_disagreement:process_wrapper')
    payload = None
    # The suite stores a command and Exit code line before the smartctl output.
    # Accept the same wrapper around JSON while rejecting arbitrary trailing text.
    json_start = text.find('{')
    if json_start >= 0:
        try:
            payload, end = json.JSONDecoder().raw_decode(text[json_start:])
            if text[json_start + end:].strip():
                result['errors'].append('unexpected_trailing_json_content')
        except (ValueError, TypeError):
            result['errors'].append('invalid_json_payload')
    if isinstance(payload, dict) and ('smartctl' in payload or 'ata_smart_attributes' in payload):
        result['serial'] = payload.get('serial_number')
        result['model'] = payload.get('model_name')
        control = payload.get('smartctl')
        reported_code = control.get('exit_status') if isinstance(control, dict) else None
        result['json_exit_code'] = reported_code
        if result['exit_code'] is None:
            result['exit_code'] = reported_code
        elif reported_code is not None and reported_code != result['exit_code']:
            result['acquisition_errors'].append(
                f"exit_status_disagreement:process={result['exit_code']},json={reported_code}")
        if isinstance(reported_code, int) and not isinstance(reported_code, bool):
            result['health_alert'] |= bool(reported_code & 0x18)
        attributes = payload.get('ata_smart_attributes')
        rows = attributes.get('table', []) if isinstance(attributes, dict) else []
        if not isinstance(rows, list):
            rows = []
            result['errors'].append('invalid_json_attribute_table')
        for row in rows:
            if (not isinstance(row, dict) or not isinstance(row.get('id'), int) or
                    isinstance(row.get('id'), bool)):
                result['errors'].append('invalid_json_attribute_row')
                continue
            raw = row.get('raw') or {}
            if not isinstance(raw, dict):
                result['errors'].append('invalid_json_attribute_raw:' + str(row['id']))
                raw = {}
            raw_text = str(raw.get('string', raw.get('value', '')))
            value = raw.get('value')
            if not isinstance(value, int) or isinstance(value, bool):
                value = _raw_integer(raw_text)
            _add_attribute(result, row['id'], str(row.get('name', 'Unknown_Attribute')),
                           value, raw_text)
        status = payload.get('smart_status')
        if isinstance(status, dict) and status.get('passed') is False:
            result['health_alert'] = True
    else:
        serial = re.search(r'^\s*Serial Number:\s*(\S+)\s*$', text, re.M | re.I)
        model = re.search(r'^\s*Device Model:\s*(.+)$', text, re.M | re.I)
        if serial:
            result['serial'] = serial.group(1)
        if model:
            result['model'] = model.group(1).strip()
        raw_index = None
        for line in text.splitlines():
            fields = line.split()
            if fields and fields[0] == 'ID#' and 'RAW_VALUE' in fields:
                raw_index = fields.index('RAW_VALUE')
                continue
            if len(fields) < 3 or not fields[0].isdigit():
                continue
            attr_id = int(fields[0])
            if not 1 <= attr_id <= 255 or not re.fullmatch(r'[\w-]+', fields[1]):
                continue
            if not (re.fullmatch(r'0x[0-9a-fA-F]+', fields[2]) or
                    re.fullmatch(r'[POSRCK-]{6}', fields[2])):
                continue
            # -A: ID NAME FLAG VALUE WORST THRESH TYPE UPDATED WHEN_FAILED RAW
            # -x: ID NAME FLAGS VALUE WORST THRESH FAIL RAW
            index = raw_index
            if index is None:
                if re.fullmatch(r'0x[0-9a-fA-F]+', fields[2]):
                    index = 9
                elif re.fullmatch(r'[POSRCK-]{6}', fields[2]):
                    index = 7
                else:
                    continue
            if len(fields) <= index:
                result['errors'].append(f'truncated_attribute:{attr_id}')
                continue
            raw_text = ' '.join(fields[index:])
            _add_attribute(result, attr_id, fields[1], _raw_integer(raw_text), raw_text)
        if re.search(r'SMART overall-health.*:\s*FAILED', text, re.I):
            result['health_alert'] = True
    if not isinstance(result['serial'], str) or not result['serial'].strip():
        result['serial'] = None
        result['errors'].append('missing_serial')
    if not result['attributes']:
        result['errors'].append('missing_attribute_table')
    rc = result['exit_code']
    if not isinstance(rc, int) or isinstance(rc, bool) or rc < 0 or rc > 255:
        result['acquisition_errors'].append('unknown_or_invalid_exit_status')
    else:
        result['exit_status_bits'] = [n for n in range(8) if rc & (1 << n)]
        if rc & 0x07:
            result['acquisition_errors'].append(f'smartctl_acquisition_error:{rc}')
        result['health_alert'] |= bool(rc & 0x18)
    result['missing_required_ids'] = sorted(REQUIRED_IDS - result['attributes'].keys(), key=int)
    if result['missing_required_ids']:
        result['errors'].append('missing_required_attributes:' + ','.join(result['missing_required_ids']))
    result['parse_complete'] = not result['errors']
    result['acquisition_complete'] = not result['acquisition_errors']
    return result


def _add_attribute(result, attr_id, name, value, raw_text):
    key = str(attr_id)
    if not 1 <= attr_id <= 255:
        result['errors'].append(f'invalid_attribute_id:{attr_id}')
        return
    if key in result['attributes']:
        result['errors'].append(f'duplicate_attribute_id:{attr_id}')
        return
    result['attributes'][key] = {'name': name, 'raw_value': value, 'raw': raw_text}
    if value is None:
        # Keep vendor text, but never invent a counter for it.
        result['errors'].append(f'non_numeric_attribute:{attr_id}')


def compare_smart(begin, end):
    """Compare records by ATA attribute ID and retain absence/raw annotations."""
    left, right = begin['attributes'], end['attributes']
    changes = {}
    for key in sorted(left.keys() & right.keys(), key=int):
        old, new = left[key], right[key]
        if old['raw_value'] != new['raw_value'] or old['raw'] != new['raw']:
            delta = (new['raw_value'] - old['raw_value']
                     if old['raw_value'] is not None and new['raw_value'] is not None else None)
            changes[key] = {'name': new['name'], 'before': old['raw_value'],
                            'after': new['raw_value'], 'delta': delta,
                            'raw_before': old['raw'], 'raw_after': new['raw']}
    missing_before = sorted(right.keys() - left.keys(), key=int)
    missing_end = sorted(left.keys() - right.keys(), key=int)
    concerning = (begin['health_alert'] or end['health_alert'] or
                  any(key in CONCERNING_IDS and v['delta'] is not None and v['delta'] > 0
                      for key, v in changes.items()))
    # A decrement of a monotonic health counter also needs review; a reset,
    # swapped record or vendor interpretation cannot count as a clean run.
    counter_decreases = [key for key, v in changes.items()
                         if key in CONCERNING_IDS and v['delta'] is not None and v['delta'] < 0]
    complete = (begin['parse_complete'] and end['parse_complete'] and
                begin['serial'] == end['serial'] and not missing_before and
                not missing_end and not counter_decreases)
    return {'baseline': left, 'end': right, 'changes': changes,
            'missing_baseline_ids': missing_before, 'missing_end_ids': missing_end,
            'counter_decreases': counter_decreases, 'parse_complete': bool(complete),
            'acquisition_complete': bool(begin['acquisition_complete'] and
                                         end['acquisition_complete']),
            'health_alert': bool(begin['health_alert'] or end['health_alert'])}, bool(concerning)
