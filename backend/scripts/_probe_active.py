import eltdx
c = eltdx.TdxClient(pool_size=2, timeout=8.0)
c.connect()
hits = ['sh880471', 'sh880491', 'sh880380', 'sh880301', 'sh880330', 'sh880318', 'sh880490']
qs = c.get_quote(hits)
for q in qs:
    total = q.total_hand or 0
    outd = q.outer_disc or 0
    ind = q.inside_dish or 0
    net = outd - ind
    pct = (net / total * 100) if total else 0.0
    print(f"{q.full_code}  total={total:>10.0f}  outer={outd:>10.0f}  inner={ind:>10.0f}  net={net:>+10.0f}  pct={pct:+.2f}%")
