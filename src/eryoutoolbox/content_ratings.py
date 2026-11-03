"""Source ratings are independent of image preferences and human review."""
import json

SENSITIVE_CODES = {'pn', 'nu', 'sc', 'ft', 'bg', 'iv'}


def preview_allowed(item, show_images, show_sensitive=False, show_unknown=False):
    if not show_images:
        return False
    evidence=item.get('source_ratings')
    values=evidence.get('codes') if isinstance(evidence,dict) else None
    codes=set(values) if isinstance(values,list) and all(isinstance(c,str) for c in values) else {'UNKNOWN'}
    if (item.get('content_rating_status') in {'ADULT','NSFW'} or codes & SENSITIVE_CODES) and not show_sensitive:
        return False
    if (codes & {'UNKNOWN','rp'} or not codes) and not show_unknown:
        return False
    return True

def source_ratings(raw):
    try:
        data = json.loads(raw or '{}') if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        data = {}
    data = data if isinstance(data, dict) else {}
    evidence = data.get('_source_rating_evidence')
    if isinstance(evidence, dict) and isinstance(evidence.get('fields'), dict):
        verified = source_ratings(evidence['fields'])
        if verified['verification'] in {'explicit_labels', 'source_unrated_flag'}:
            verified['observed_at'] = evidence.get('observed_at')
            return verified
    record = data.get('_record', data)
    record = record if isinstance(record, dict) else {}
    fields = record.get('source_rating_fields', record)
    fields = fields if isinstance(fields, dict) else {}
    fields = {k: fields[k] for k in ('_aContentRatings','_bHasContentRatings','_sInitialVisibility') if k in fields}
    ratings = fields.get('_aContentRatings')
    if isinstance(ratings, dict) and ratings and all(isinstance(k, str) and k and k==k.strip() and isinstance(v, str) and v.strip() for k,v in ratings.items()):
        return {'codes': list(ratings), 'verification': 'explicit_labels', 'raw': fields}
    flag = fields.get('_bHasContentRatings', record.get('has_content_ratings'))
    if isinstance(flag, bool):
        fields.setdefault('_bHasContentRatings', flag)
    if flag is False:
        return {'codes': ['-'], 'verification': 'source_unrated_flag', 'raw': fields}
    return {'codes': ['UNKNOWN'], 'verification': 'unverified_labels',
            'raw': {k:fields[k] for k in ('_aContentRatings','_bHasContentRatings','_sInitialVisibility') if k in fields}}

def rating_matches(raw, selected):
    return bool(set(source_ratings(raw)['codes']) & set(json.loads(selected)))


def save_verified_samples(connection, report, *, dry_run=True, before_write=None):
    """Enrich existing rows only; metadata, images and human states stay intact."""
    from datetime import datetime
    if report.get('format') != 'eryoutoolbox-rating-audit-v1':
        raise ValueError('Unrecognized audit report')
    observed = datetime.fromisoformat(report['observed_at'].replace('Z', '+00:00'))
    if observed.tzinfo is None:
        raise ValueError('Audit timestamp must include UTC offset')
    samples = report.get('samples')
    if not isinstance(samples, list) or len(samples) > 20:
        raise ValueError('Report must contain at most 20 samples')
    result = {'matched': 0, 'candidates': 0, 'updated': 0, 'skipped': 0, 'unchanged': 0}
    if not dry_run:
        connection.execute('BEGIN IMMEDIATE')
    try:
        changes = []
        seen = set()
        for sample in samples:
            item_id = sample.get('item_id')
            fields = sample.get('detail')
            if (sample.get('source') != 'gamebanana' or sample.get('item_type') != 'Mod'
                    or type(item_id) is not int or item_id < 1 or item_id in seen
                    or sample.get('http_status') != 200
                    or source_ratings(fields)['verification'] not in {'explicit_labels', 'source_unrated_flag'}):
                result['skipped'] += 1
                continue
            seen.add(item_id)
            row = connection.execute("SELECT raw_metadata_json FROM mods WHERE source='gamebanana' AND item_type='Mod' AND item_id=?", (item_id,)).fetchone()
            if row is None:
                result['skipped'] += 1
                continue
            result['matched'] += 1
            try:
                data = json.loads(row[0] or '{}')
                if not isinstance(data, dict):
                    raise ValueError('Invalid existing metadata')
                previous = data.get('_source_rating_evidence', {})
                previous_time = previous.get('observed_at')
                if previous_time and datetime.fromisoformat(previous_time.replace('Z', '+00:00')) > observed:
                    result['skipped'] += 1
                    continue
            except (ValueError, TypeError, AttributeError):
                result['skipped'] += 1
                continue
            fields = source_ratings(fields)['raw']
            if previous.get('fields') == fields:
                result['unchanged'] += 1
                continue
            data['_source_rating_evidence'] = {'fields': fields, 'observed_at': report['observed_at'],
                                               'endpoint': f'https://gamebanana.com/apiv11/Mod/{item_id}/ProfilePage'}
            changes.append((json.dumps(data, ensure_ascii=False), item_id))
        result['candidates'] = len(changes)
        if not dry_run:
            if changes:
                if before_write is None:
                    raise ValueError('Backup is required')
                before_write()
                connection.executemany("UPDATE mods SET raw_metadata_json=? WHERE source='gamebanana' AND item_type='Mod' AND item_id=?", changes)
                result['updated'] = len(changes)
            connection.commit()
        return result
    except BaseException:
        if not dry_run:
            connection.rollback()
        raise
