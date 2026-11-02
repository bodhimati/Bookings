#!/usr/bin/env python3
"""LBC Weekly Bookings dashboard refresh.

Usage (run from the work folder that holds history.json, series/, orders/, voided/):
  python3 refresh.py select YYYY-MM-DD   -> writes selected.json, prints series to fetch
  python3 refresh.py build  YYYY-MM-DD   -> writes upcoming_<date>.csv, booking_curves_<date>.csv,
                                            updated history.json, prints table + checks

Data rules (agreed with Bodhimati, Oct 2026):
- A place counts if: line type "ticket", order not cancelled, has a ticket ID, ticket not voided. Coach seats separate.
- Retreats: Vajrasana series + Adhisthana Winter Retreat (split into All 10 / First 5 / Last 5 days).
  Deposit + "Final/Balance Payment" series combined by start date; places counted from deposit series.
- Excluded: ROWE / Regional Order Weekend, ordination, Buddha Day, tests, coach-only, TEAM, one-off workshops.
- Courses: LBC multi-week courses (an occurrence lasting 14+ days), one occurrence = one run.
- Revenue = valid ticket line totals (deposit + final), minus "£X off" gift cards; coach and donations excluded.
- Past runs = last three finished runs of the same type. Pace vs their places at the same days before start.
"""
import json, csv, glob, os, re, sys, datetime, collections

D = datetime.date.fromisoformat
EXCL = re.compile(r'ROWE|Regional Order|Ordination|Buddha Day|\btest\b|TEST|Coach|TEAM|Qigong|Kum Nye|Hidden Notes|Inside Sound|Burr Island|Poetry|Philosophy|Yoga Class|Yoga Afternoon|Yoga Morning|Restorative|Solstice|Mindful Movement|Day Retreat|Free Your Mind|Tibetan Book|Breaking through|Meditation Challenge', re.I)
OFFCARD = re.compile(r'^\s*£?\d+\s*off', re.I)


def lj(f):
    d = json.load(open(f))
    if isinstance(d, list):
        d = json.loads(d[0]['text'])
    return d


def load_series():
    S = {}
    for f in sorted(glob.glob('series/*.json')):
        for s in lj(f)['data']:
            S[s['id']] = s
    return S


def pages(kind, sid):
    k = int(open(f'{kind}/{sid}.{"odone" if kind == "orders" else "vdone"}').read().strip())
    out = []
    for p in range(1, k + 1):
        out += lj(f'{kind}/{sid}_p{p}.json')['data']
    return out


def valid_lines(sids):
    out, off = [], []
    for sid in sids:
        vo = {t['id'] for t in pages('voided', sid)}
        for o in pages('orders', sid):
            if o['status'] == 'cancelled':
                continue
            for li in o['line_items']:
                if li['type'] == 'gift_card' and OFFCARD.match(li['description']):
                    off.append((sid, o, li))
                if li['type'] != 'ticket':
                    continue
                q = li['quantity'] or 1
                for f in (li.get('fulfilments') or []):
                    r = f.get('reference_id')
                    if r and r not in vo:
                        out.append((sid, o, li, r, li['total'] / q / 100))
    return out, off


def gender_of(d):
    d = d.lower()
    if re.search(r"\bmen's|\bmale\b", d): return 'men'
    if re.search(r"women's|female", d): return 'women'
    if re.search(r'mixed|non-binary|gender-neutral', d): return 'mixed'
    return None


def is_final(n): return bool(re.search(r'final payment|balance payment', n, re.I))


def rtype(n):
    n = n.replace(' and ', ' & ')
    rules = [(r'Winter Intensive', 'Winter Intensive Retreat'),
             (r"Men's (Intensive )?Long Weekend", "Men's Intensive Long Weekend"), (r"Women's (Intensive )?Long Weekend", "Women's Intensive Long Weekend"),
             (r"Women's Intensive", "Women's Intensive Retreat"), (r"Men's Intensive", "Men's Intensive Retreat"),
             (r'Sub25|IGNITE|Sub30 Weekend', '18–30s Weekend (Sub25 / IGNITE / Sub30)'), (r'Immersion', 'Buddhism & Meditation Immersion'),
             (r'Long Weekend', 'Buddhism & Meditation Long Weekend'), (r'B.*Meditation Weekend', 'Buddhism & Meditation Weekend'),
             (r'LGBTQIA', 'LGBTQIA+ Weekend'), (r'People of Colour Weekend', 'People of Colour Weekend'), (r'People of Colour Retreat', 'People of Colour Retreat'),
             (r'12-Step', 'Buddhism & 12-Step Weekend'), (r'Deep Ecology', 'Buddhism & Deep Ecology Retreat'), (r'Yoga for Meditation Weekend', 'Yoga for Meditation Weekend'),
             (r'Yoga for Meditation Retreat', 'Yoga for Meditation Retreat'), (r'Going for Refuge', 'Going for Refuge Retreat for women')]
    for p, t in rules:
        if re.search(p, n): return t
    return n.split(':')[0].replace(' - Final Payment', '').strip()


def ctype(n):
    if re.search('Life [Ww]ith', n): return 'Life With Full Attention'
    if 'Deepen' in n: return 'Deepen your Yoga Practice'
    return n


def venue(s): return (s.get('venue') or {}).get('name') or ''


def is_wr(s): return 'Winter Retreat' in s['name'] and 'Intensive' not in s['name'] and venue(s) == 'Adhisthana Retreat Centre'


def kind_of(s):
    n = s['name']
    if EXCL.search(n): return None
    if venue(s) == 'Vajrasana Retreat Centre' or is_wr(s): return 'retreat'
    if venue(s) in ('Yoga', 'Mandala Cafe', 'Mandala Café', 'Guhyaloka', 'Adhisthana Retreat Centre'): return None
    if not any(t['price'] > 0 for t in s['default_ticket_types']): return None
    return 'course'


def series_cap(s, gender=None):
    cap = 0
    for gr in s['default_ticket_groups']:
        nm = gr['name'].lower()
        if 'coach' in nm: continue
        g = 'women' if ('women' in nm or 'female' in nm) else 'men' if re.search(r"\bmen|\bmale", nm) else 'other'
        if gender and g != gender: continue
        tts = [t for t in s['default_ticket_types'] if t['id'] in gr['ticket_ids']]
        cap += gr['max_quantity'] or max([t['quantity_total'] for t in tts] or [0])
    if not gender:
        for t in s['default_ticket_types']:
            if not t.get('group_id') and 'coach' not in t['name'].lower(): cap += t['quantity_total']
    return cap


def course_caps(s):
    ci = co = 0
    for gr in s['default_ticket_groups']:
        tts = [t for t in s['default_ticket_types'] if t['id'] in gr['ticket_ids']]
        mq = gr['max_quantity'] or max([t['quantity_total'] for t in tts] or [0])
        if 'online' in gr['name'].lower(): co += mq
        else: ci += mq
    if not s['default_ticket_groups']:
        ci = max([t['quantity_total'] for t in s['default_ticket_types'] if 'online' not in t['name'].lower()] or [0])
    return ci, co


def full_price(s):
    best = None
    for t in s['default_ticket_types']:
        n = t['name'].lower()
        if 'full' in n and 'deposit' not in n and 'final' not in n and 'coach' not in n and 'online' not in n:
            best = max(best or 0, t['price'] / 100)
    return best


# ------------------------------------------------------------------ select
def cmd_select(today):
    S = load_series(); H = json.load(open('history.json'))
    end = today + datetime.timedelta(days=95)
    sel = set(H.get('pending', []))
    for sid, s in S.items():
        if not kind_of(s) or not s.get('upcoming_occurrences'): continue
        nd = (s.get('next_occurrence_date') or {}).get('date')
        if nd and D(nd) <= end: sel.add(sid)
    # retreats: also the matching final-payment series for any selected deposit series (same name stem)
    json.dump(sorted(sel), open('selected.json', 'w'))
    print(len(sel), 'series to fetch:')
    for sid in sorted(sel): print(sid, S.get(sid, {}).get('name', '(from last week)'))


# ------------------------------------------------------------------ build
def cmd_build(today):
    S = load_series(); H = json.load(open('history.json'))
    hist = H['runs']
    sel = [s for s in json.load(open('selected.json')) if os.path.exists(f'orders/{s}.odone') and s in S]
    runs = {}
    checks = []
    for sid in sel:
        s = S[sid]; kind = kind_of(s)
        if not kind: continue
        L, off = valid_lines([sid])
        issued = sum(t['quantity_issued'] for t in s['default_ticket_types'])
        if s.get('total_occurrences') == 1:
            checks.append((sid, s['name'], len(L), issued))
        fin = is_final(s['name'])
        for _, o, li, ref, amt in L:
            es = li['event_summary']; st = es['start_date'][:10]; en = es['end_date'][:10]
            od = o['created_at'][:10]
            if kind == 'course':
                if (D(en) - D(st)).days < 14: continue
                key = 'C|' + es['event_id']
                r = runs.setdefault(key, dict(name=s['name'], type=ctype(s['name']), kind='course', start=st, end=en, places=[], income=[],
                                              sids=set(), modes=collections.Counter(), g=collections.Counter()))
                r['places'].append(od); r['income'].append([od, amt]); r['sids'].add(sid)
                r['modes']['online' if 'online' in li['description'].lower() else 'in-person'] += 1
                continue
            if is_wr(s):
                part = 'All 10 days' if 'All 10' in s['name'] else ('First 5 days' if 'First 5' in s['name'] else 'Last 5 days')
                yr = st[:4] if st[5:7] == '12' else str(int(st[:4]) - 1)
                key = f'WR|{yr}|{part}'
                r = runs.setdefault(key, dict(name=f'Winter Retreat – {part}', type=f'WR {part}', kind='retreat',
                                              start={'All 10 days': f'{yr}-12-22', 'First 5 days': f'{yr}-12-22', 'Last 5 days': f'{yr}-12-27'}[part],
                                              end=None, places=[], income=[], sids=set(), deps=set(), g=collections.Counter()))
            else:
                key = 'R|' + st
                r = runs.setdefault(key, dict(name=None, type=None, kind='retreat', start=st, end=None, places=[], income=[], sids=set(), deps=set(), g=collections.Counter()))
                if not fin and not r['name']: r['name'] = s['name']; r['type'] = rtype(s['name'])
                if not fin and (not r['end'] or en > r['end']): r['end'] = en
            r['sids'].add(sid)
            if 'coach' in li['description'].lower(): continue
            r['income'].append([od, amt])
            if not fin:
                r['places'].append(od); r['deps'].add(sid)
                single = 'men' if re.search(r"\bmen's", r['name'] or '', re.I) else ('women' if re.search('women', r['name'] or '', re.I) else None)
                r['g'][gender_of(li['description']) or single or 'other'] += 1
        for _, o, li in off:
            es = li.get('event_summary') or {}
            st = es.get('start_date', '')[:10]
            if not st: continue
            if kind == 'course': key = 'C|' + es.get('event_id', '')
            elif is_wr(s):
                part = 'All 10 days' if 'All 10' in s['name'] else ('First 5 days' if 'First 5' in s['name'] else 'Last 5 days')
                yr = st[:4] if st[5:7] == '12' else str(int(st[:4]) - 1); key = f'WR|{yr}|{part}'
            else: key = 'R|' + st
            if key in runs: runs[key]['income'].append([o['created_at'][:10], li['total'] / 100])
    # capacities / prices
    for k, r in runs.items():
        if r['kind'] == 'course':
            s = S[sorted(r['sids'])[0]]; ci, co = course_caps(s); r['capacity'] = ci; r['fp'] = full_price(s)
        else:
            deps = [S[x] for x in r.get('deps', [])]
            r['capacity'] = sum(series_cap(x) for x in deps) or None
            r['men_cap'] = sum(series_cap(x, 'men') for x in deps) or None
            r['women_cap'] = sum(series_cap(x, 'women') for x in deps) or None
            r['fp'] = max([full_price(x) or 0 for x in deps] or [0]) or None
            if not r['name']: r['name'] = S[sorted(r['sids'])[0]]['name']; r['type'] = rtype(r['name'])
    # move started runs into history, keep upcoming
    end = today + datetime.timedelta(days=92)
    pending = set()
    upcoming = {}
    for k, r in runs.items():
        if D(r['start']) <= today:
            if r['places']:
                hist[k] = dict(name=r['name'], type=r['type'], kind=r['kind'], start=r['start'], end=r['end'], capacity=r['capacity'], fp=r['fp'],
                               places=sorted(r['places']), income=[[a, round(b, 2)] for a, b in r['income']])
        else:
            pending |= r['sids']
            if D(r['start']) <= end: upcoming[k] = r
    H['runs'] = hist; H['pending'] = sorted(pending); H['updated'] = str(today)
    json.dump(H, open('history.json', 'w'), separators=(',', ':'))

    def cp(r, d): st = D(r['start']); return sum(1 for p in r['places'] if (st - D(p)).days >= d)
    def nights(r): return (D(r['end']) - D(r['start'])).days if r.get('end') else 0
    up = sorted(upcoming.items(), key=lambda kr: (kr[1]['start'], kr[1]['name']))
    feat = set()
    c = [k for k, r in up if r['kind'] == 'course' and 'Introduction to Buddhism' not in r['name']]
    if c: feat.add(c[0])
    rt = [k for k, r in up if r['kind'] == 'retreat' and nights(r) >= 4 and not k.startswith('WR') and 'Winter Intensive' not in r['name']]
    if rt: feat.add(rt[0])
    rows, curves = [], []
    for i, (k, r) in enumerate(up):
        st = D(r['start']); dout = (st - today).days; key = f"{r['start']}-{i}"
        winter = k.startswith('WR') or 'Winter Intensive' in r['name']
        section = 'featured' if k in feat else ('winter' if winter else 'main')
        prev = sorted([(k2, r2) for k2, r2 in hist.items() if r2['type'] == r['type'] and D(r2['start']) < today and r2['places']], key=lambda kr: kr[1]['start'])[-3:]
        booked = len(r['places']); rev = round(sum(a for _, a in r['income'])); cap = r['capacity'] or None
        window = 150 if winter else (90 if r['kind'] == 'retreat' else 60)
        row = dict(key=key, as_of=str(today), section=section, event=r['name'], type=r['kind'].title(), start=r['start'], days_to_go=dout, window_days=window,
                   booked=booked, new_7d=sum(1 for p in r['places'] if str(today - datetime.timedelta(days=7)) < p <= str(today)), capacity=cap, spaces_left=(cap - booked) if cap else None, pct_booked=round(booked / cap, 3) if cap else None, revenue=rev,
                   past_by_now=None, occ_booked=booked if r['kind'] == 'retreat' else r['modes'].get('in-person', 0),
                   men=None, men_cap=None, women=None, women_cap=None, other=None, predicted_places=None, predicted_revenue=None,
                   status='New – no past run', target_booked=None, target_spaces_left=None, target_pct=None, target_revenue=None)
        if r['kind'] == 'retreat':
            g = r['g']
            row.update(men=g['men'], men_cap=r.get('men_cap'), women=g['women'], women_cap=r.get('women_cap'), other=g['mixed'] + g['other'])
        if prev:
            n = len(prev); byn = sum(cp(r2, dout) for _, r2 in prev) / n
            fin = [len(r2['places']) for _, r2 in prev]
            row['past_by_now'] = round(byn, 1)
            row['status'] = 'Ahead' if booked >= byn + 1 else ('Behind' if booked <= byn - 1 else 'On track')
            pp = booked + sum(f - cp(r2, dout) for f, (_, r2) in zip(fin, prev)) / n
            if cap: pp = min(cap, pp)
            per = sum((sum(a for _, a in r2['income']) / len(r2['places'])) * ((r['fp'] / r2['fp']) if r.get('fp') and r2.get('fp') else 1) for _, r2 in prev) / n
            row['predicted_places'] = round(pp); row['predicted_revenue'] = round(max(rev, pp * per))
            t = round(sum(fin) / n); t = min(t, cap) if cap else t
            row.update(target_booked=t, target_spaces_left=(cap - t) if cap else None, target_pct=round(t / cap, 3) if cap else None,
                       target_revenue=round(sum(sum(a for _, a in r2['income']) for _, r2 in prev) / n))
        rows.append(row)
        for d in range(window, -1, -1):
            if d >= dout: curves.append(dict(key=key, run='This run', current=1, days_before=d, bookings=cp(r, d)))
        for k2, r2 in prev:
            lab = D(r2['start']).strftime('%b %Y')
            for d in range(window, -1, -1): curves.append(dict(key=key, run=lab, current=0, days_before=d, bookings=cp(r2, d)))
    order = {'featured': 0, 'main': 1, 'winter': 2}
    def wrank(e):
        for i, p in enumerate(['All 10', 'First 5', 'Last 5', 'Intensive']):
            if p in e: return i
        return 9
    rows.sort(key=lambda x: (order[x['section']], wrank(x['event']) if x['section'] == 'winter' else 0, x['start'], x['event']))

    def w(fn, L):
        with open(fn, 'w', newline='') as f:
            wr = csv.DictWriter(f, fieldnames=list(L[0].keys())); wr.writeheader()
            for x in L: wr.writerow({k: ('' if v is None else v) for k, v in x.items()})
    w(f'upcoming_{today}.csv', rows); w(f'booking_curves_{today}.csv', curves)
    health = build_health(today, hist, runs, rows)
    w(f'health_{today}.csv', health)
    print('ROWS')
    for x in rows: print(x['section'], '|', x['event'], '|', x['start'], '| booked', x['booked'], '/', x['capacity'], '| £', x['revenue'], '|', x['status'])
    print('CHECKS (valid places incl. coach vs Ticket Tailor issued; should match)')
    for sid, n, v, iss in checks: print(('OK  ' if v == iss else 'DIFF'), sid, n, v, iss)


def build_health(today, hist, runs, rows, weeks=26, occ_days=84, dem_days=28):
    """Weekly health series for the dials (one row per week, oldest first; the last row is today).

    occ_*      Occupancy: retreats (beds) that FINISHED in the 12 weeks to that date: places ÷ beds.
    ahead_*    Anticipated (last row only): retreats starting in the next 12 weeks, predicted final
               places (booked so far, incl. this week, plus what past runs added from this point) ÷ beds.
    week_places Retreat places booked in the 7 days to that date.
    dem_*      Demand: places booked in the 4 weeks to that date, for anything with past runs, ÷ what its
               last three runs booked over the same stretch before their start (100% = level with past).
    """
    allr = {}
    for k, r in hist.items(): allr[k] = r
    for k, r in runs.items():
        if r['places']: allr[k] = dict(r, places=sorted(r['places']))
    def end_of(k, r):
        if r.get('end'): return D(r['end'])
        if k.startswith('WR'): return D(r['start']) + datetime.timedelta(days=10 if 'All 10' in k else 5)
        return D(r['start'])
    rets = [(k, r) for k, r in allr.items() if r['kind'] == 'retreat' and r.get('capacity')]
    bytype = collections.defaultdict(list)
    for k, r in allr.items(): bytype[r['type']].append(r)
    for t in bytype: bytype[t].sort(key=lambda r: r['start'])
    def prev3(r):
        return [p for p in bytype[r['type']] if p['start'] < r['start']][-3:]
    def between(r, a, b):  # places booked with order date in (a, b], before the start
        st = r['start']
        return sum(1 for p in r['places'] if str(a) < p <= str(b) and p <= st)
    out = []
    for i in range(weeks, -1, -1):
        d = today - datetime.timedelta(days=7 * i)
        fin = [(k, r) for k, r in rets if d - datetime.timedelta(days=occ_days) < end_of(k, r) <= d]
        op = sum(len(r['places']) for _, r in fin); ob = sum(r['capacity'] for _, r in fin)
        wk = sum(between(r, d - datetime.timedelta(days=7), d) for _, r in rets)
        a = d - datetime.timedelta(days=dem_days)
        act = exp = 0.0
        for k, r in allr.items():
            st = D(r['start'])
            if st <= a: continue
            pv = prev3(r)
            if not pv: continue
            act += between(r, a, d)
            e = 0
            for p in pv:
                ps = D(p['start'])
                e += between(p, ps - (st - a), ps - (st - d))
            exp += e / len(pv)
        out.append(dict(date=str(d), occ=round(op / ob, 3) if ob else None, occ_places=op, occ_beds=ob, occ_runs=len(fin),
                        week_places=wk, dem=round(act / exp, 3) if exp else None, dem_actual=round(act), dem_expected=round(exp, 1),
                        ahead=None, ahead_places=None, ahead_beds=None, ahead_runs=None))
    # anticipated: retreats starting in the next 12 weeks
    end = today + datetime.timedelta(days=occ_days)
    up = [x for x in rows if x['type'] == 'Retreat' and x['capacity'] and D(x['start']) <= end]
    ap = sum((x['predicted_places'] if x['predicted_places'] is not None else x['booked']) for x in up)
    ab = sum(x['capacity'] for x in up)
    out[-1].update(ahead=round(ap / ab, 3) if ab else None, ahead_places=ap, ahead_beds=ab, ahead_runs=len(up))
    return out


if __name__ == '__main__':
    cmd, day = sys.argv[1], D(sys.argv[2])
    {'select': cmd_select, 'build': cmd_build}[cmd](day)
