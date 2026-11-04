"""Deterministic, account-scoped request matching and event-time conversion."""

import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def zone(value):
    if not isinstance(value, str) or len(value) > 80:
        raise ValueError('无效时区')
    fixed = re.fullmatch(r'UTC(?:([+-])(\d{1,2})(?::(\d{2}))?)?', value, re.I)
    if fixed:
        minutes = int(fixed[2] or 0) * 60 + int(fixed[3] or 0)
        if minutes > 14 * 60 or int(fixed[3] or 0) > 59:
            raise ValueError('无效 UTC 偏移')
        return timezone(timedelta(minutes=minutes * (-1 if fixed[1] == '-' else 1)))
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError('无法识别时区，请选择有效的 IANA 时区或 UTC 偏移') from None


def instant(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError('UTC 查询时间必须包含偏移量')
    return parsed.astimezone(timezone.utc)


def time_evidence(value, name=None):
    moment = instant(value)
    name = name or 'UTC'
    return {'utc': moment.isoformat(timespec='seconds'), 'time_zone': name,
            'local': moment.astimezone(zone(name)).isoformat(timespec='seconds')}


def explicit_zone(text):
    match = re.search(r'UTC\s*([+-])\s*(\d{1,2})(?::(\d{2}))?', text, re.I)
    if match:
        value = f'UTC{match[1]}{int(match[2]):02d}:{match[3] or "00"}'
        zone(value)
        return value
    for label, name in [('北京时间', 'Asia/Shanghai'), ('上海时间', 'Asia/Shanghai'),
                        ('中国时间', 'Asia/Shanghai'), ('悉尼时间', 'Australia/Sydney')]:
        if label in text:
            return name
    match = re.search(r'\b(?:Australia|Asia|Europe|America|Pacific|Africa)/[A-Za-z_]+(?:/[A-Za-z_]+)?\b', text)
    if match:
        zone(match[0])
        return match[0]
    if re.search(r'\bUTC\b', text, re.I):
        return 'UTC'
    return None


def request_id(text):
    found = re.search(r'(?:请求(?:编号|\s*ID)?|request\s*(?:id)?)\s*[:：#＃]?\s*(\d+)\b|(?<!\w)[#＃](\d+)\b', text, re.I)
    return int(found[1] or found[2]) if found else None


DATE = re.compile(r'(?:(\d{4})[-/年])?(\d{1,2})[-/月](\d{1,2})日?[ T]*(\d{1,2})[:：](\d{2})(?::(\d{2}))?')


def parse_context(text, payload=None, *, received_at):
    payload = payload or {}
    selected = payload.get('time_zone')
    if selected:
        zone(selected)
    source = payload.get('timezone_source', 'browser' if selected else 'unknown')
    if source not in {'browser', 'selected', 'unknown'}:
        raise ValueError('无效时区来源')
    explicit = explicit_zone(text)
    result = {'time_zone': explicit or selected, 'timezone_source': 'explicit' if explicit else source, 'display_time_zone': selected, 'display_timezone_source': source}
    linked = payload.get('request_id')
    if linked is not None and (type(linked) is not int or linked <= 0):
        raise ValueError('请求编号必须为正整数')
    mentioned = request_id(text)
    if linked and mentioned and linked != mentioned:
        raise ValueError('关联请求编号与正文不一致，请核对后再提交')
    if linked or mentioned:
        result['request_id'] = linked or mentioned
        result['association_source'] = 'structured' if linked else 'text'
    model = re.search(r'\b(?:gpt|claude|grok|gemini|deepseek)[-\w.]+', text, re.I)
    if model:
        result['model'] = model[0].rstrip('.')
    status = re.search(r'(?:HTTP|返回|报错|错误|状态码)\s*([45]\d{2})\b|\b([45]\d{2})\s*(?:错误|报错)', text, re.I)
    if status:
        result['status_code'] = int(status[1] or status[2])
    error = re.search(r'(?:错误(?:码|信息|文字)?|报错|error)\s*(?:为|是|[:：=])?\s*([A-Za-z][\w.-]*_[\w.-]+)', text, re.I)
    if error:
        result['error'] = error[1].rstrip('.')
    match = DATE.search(text)
    if not match:
        clock = re.search(r'(今天|昨天)\s*(\d{1,2})[:：](\d{2})(?::(\d{2}))?', text)
        if clock and result['time_zone']:
            day = instant(received_at).astimezone(zone(result['time_zone'])).date() - timedelta(days=clock[1] == '昨天')
            return parse_context(text[:clock.start()] + f'{day.isoformat()} {clock[2]}:{clock[3]}' + (f':{clock[4]}' if clock[4] else '') + text[clock.end():], payload, received_at=received_at)
        if clock or re.search(r'\d{1,2}[:：]\d{2}', text):
            result['time_issue'] = '已收到钟点和时区，只需补充完整日期（含年份），无需重复其他信息。' if result['time_zone'] else '请补充完整日期（含年份）及事件所用时区，以便定位这次请求。'
        return result
    result['reported_local_time'] = match[0]
    suffix = re.match(r'(Z|[+-]\d{2}:\d{2})\b', text[match.end():])
    if suffix and not explicit:
        result.update(time_zone='UTC' if suffix[0] == 'Z' else 'UTC' + suffix[0], timezone_source='explicit')
    if not match[1]:
        result['time_issue'] = '发生时间缺少年份，请确认年份；已有可核对的请求编号时无需重复补充。'
        return result
    if not result['time_zone']:
        result['time_issue'] = '发生时间缺少时区，请说明当时使用北京时间、悉尼时间或其他时区。'
        return result
    try:
        wall = datetime(*[int(x or 0) for x in match.groups()])
        tz = zone(result['time_zone'])
        candidates = {wall.replace(tzinfo=tz, fold=fold).astimezone(timezone.utc) for fold in (0, 1)
                      if wall.replace(tzinfo=tz, fold=fold).astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None) == wall}
    except ValueError:
        result['time_issue'] = '日期或时间无效，请核对。'
        return result
    if len(candidates) != 1:
        result['time_issue'] = ('该本地时间因夏令时切换出现两次，请补充当时的 UTC 偏移或请求编号。' if candidates
                                else '该本地时间在夏令时跳转中不存在，请核对时间或提供请求编号。')
        return result
    start = candidates.pop()
    result['start_utc'] = start.isoformat(timespec='seconds')
    result['end_utc'] = (start + timedelta(seconds=1 if match[6] else 60)).isoformat(timespec='seconds')
    return result


QUERY_KEYS = {'request_id', 'start_utc', 'end_utc', 'model', 'status_code', 'error', 'time_zone'}


def select_context(message, conversation, state, focus):
    """Carry references, never borrow the operator's timezone or another topic's ID."""
    import json
    current = json.loads(message.get('request_context_json') or '{}') or parse_context(message['content'], received_at=message['created_at'])
    reference = focus.get('reference_question')
    if reference:
        old = next((m for m in reversed(conversation.get('conversation', []))
                    if m['speaker'] == 'customer' and m['content'].startswith(reference)), None)
        base = dict(old.get('request_context', {})) if old else parse_context(reference, received_at=message['created_at'])
    else:
        base = dict(state.get('request_focus', {}))
    has_selection = any(key in current for key in ('request_id', 'start_utc', 'reported_local_time', 'time_issue'))
    returning = bool(re.search(r'回到|切回|再问(?:之前|原来)', message['content']))
    new_topic = focus.get('explicit_switch') and not reference and not returning
    new_request = bool(re.search(r'另[一个条次]+|新的请求|换.{0,3}请求', message['content']))
    if has_selection or new_topic or new_request or (current.get('model') and base.get('model') and current['model'] != base['model']):
        result = current
    else:
        result = {**base, **{k: v for k, v in current.items() if v is not None}}
        if (base.get('start_utc') or base.get('linked_time')) and current.get('timezone_source') in {'browser', 'unknown'}:
            result['time_zone'] = base.get('time_zone')
            result['timezone_source'] = base.get('timezone_source', 'unknown')
        if base.get('reported_local_time') and current.get('timezone_source') == 'explicit':
            reparsed = parse_context(base['reported_local_time'], {'time_zone': current['time_zone'], 'timezone_source': 'selected'}, received_at=message['created_at'])
            result.pop('time_issue', None)
            result.update(reparsed, timezone_source='explicit')
    return result


def lookup(db, user_id, arguments, *, queried_at):
    args = dict(arguments)
    name = args.get('time_zone') or 'UTC'
    zone(name)
    clauses, values = ['user_id=?'], [user_id]
    specific = bool(args.get('request_id') or args.get('start_utc'))
    if args.get('request_id') is not None:
        if type(args['request_id']) is not int or not 0 < args['request_id'] < 2**63:
            raise ValueError('无效请求编号')
        clauses.append('id=?'); values.append(args['request_id'])
        basis = 'request_id'
    elif args.get('start_utc'):
        start, end = instant(args['start_utc']), instant(args.get('end_utc', ''))
        if not start < end <= start + timedelta(days=31):
            raise ValueError('查询区间无效')
        clauses.extend(['julianday(created_at)>=julianday(?)', 'julianday(created_at)<julianday(?)'])
        values.extend([start.isoformat(), end.isoformat()])
        basis = 'time_range'
    else:
        clauses.append('julianday(created_at)>=julianday(?)')
        values.append((instant(queried_at) - timedelta(hours=24)).isoformat())
        basis = 'recent_summary'
    if basis != 'request_id':
        for key in ('model', 'status_code', 'error'):
            if key in args:
                if key == 'status_code' and (type(args[key]) is not int or not 100 <= args[key] <= 599):
                    raise ValueError('无效状态码')
                if key != 'status_code' and (not isinstance(args[key], str) or len(args[key]) > 160):
                    raise ValueError('无效请求筛选值')
                clauses.append(key + '=?'); values.append(args[key])
    where = ' AND '.join(clauses)
    rows = db.all('SELECT id,model,channel,status_code,error,cost_units,latency_ms,created_at,billing_source,api_key_id FROM request_logs WHERE ' + where + ' ORDER BY created_at DESC,id DESC LIMIT 30', values)
    total = db.one('SELECT COUNT(*) AS n FROM request_logs WHERE ' + where, values)['n']
    conflicts = []
    for row in rows:
        row['display_time'] = time_evidence(row['created_at'], name)
        if basis == 'request_id':
            for key in ('model', 'status_code', 'error'):
                if key in args and args[key] != row[key]:
                    conflicts.append({'field': key, 'reported': args[key], 'recorded': row[key]})
            if args.get('start_utc') and not instant(args['start_utc']) <= instant(row['created_at']) < instant(args['end_utc']):
                conflicts.append({'field': 'time', 'reported': args['start_utc'], 'recorded': row['created_at']})
    failed = [r for r in rows if r['status_code'] >= 400]
    return {'window_hours': 24 if basis == 'recent_summary' else None, 'match_basis': basis,
            'specific': specific, 'requested_id': args.get('request_id'), 'requests': rows, 'count': len(rows),
            'total_matches': total, 'truncated': total > len(rows), 'ambiguous': specific and total > 1,
            'conflicts': conflicts, 'matched': specific and total == 1 and not conflicts,
            'failed_count': len(failed), 'failed_cost_units': sum(r['cost_units'] for r in failed), 'queried_at': queried_at}
