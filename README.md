# cadis

`cadis` is the single public control layer of the Cadis system.

It orchestrates:
- dataset install and bootstrap lifecycle
- world resolution and runtime execution coordination
- deterministic state to user-facing actions
- SDK + CLI + REST integration surfaces

## Install

```bash
pip install cadis
```

## Quick Start (CLI)

```bash
cadis lookup 41.8785708032352 12.505896501941912
```

Typical flow:

- If the country dataset is already installed, Cadis prints `Region: ...` immediately.
- If the dataset is missing but supported, Cadis offers to download it and retries the lookup after install.
- Sea and offshore results are shown directly in human-readable form.

## Quick Start (SDK)

```python
from cadis import CadisSDK

sdk = CadisSDK()
out = sdk.lookup(25.0330, 121.5654)
print(out["execution"]["lookup_status"])
```

## Interaction Modes

- CLI guide: [`docs/cli.md`](docs/cli.md)
- SDK guide: [`docs/sdk.md`](docs/sdk.md)
- Docker/REST guide: [`docs/rest.md`](docs/rest.md)
- Deployment guide: [`docs/deployment.md`](docs/deployment.md)
- CI/CD examples: [`docs/cicd-examples.md`](docs/cicd-examples.md)
- Stable release manifest: [`releases/stable.json`](releases/stable.json)
- Stable manifest updater: [`scripts/update_stable_release_manifest.py`](scripts/update_stable_release_manifest.py)

## Core APIs

- `lookup(lat, lon)`
- `lookup_many(points=[{"id": "...", "lat": ..., "lon": ...}])`
- `bootstrap(iso2, ...)`
- `reinstall(iso2, ...)`
- `info()`
- `CadisSDK`
- `CadisRemoteSDK`

## Dataset Lockdown

By default, Cadis serves lookups from any installed dataset in the cache folder.

To restrict serving to a subset of installed country datasets, set:

```bash
export CADIS_ALLOWED_ISO2=TW,JP
```

When enabled, Cadis fails lookups outside the allowlist with `state.dataset.status = "blocked"` and refuses bootstrap/reinstall for those countries.

## Hierarchy Repair Model

Cadis treats dataset artifacts as read-only facts and performs lookup-time
interpretation only. Polygon evidence remains the primary source for
administrative hierarchy results.

When polygon evidence is missing an intermediate administrative level, Cadis may
use the dataset `hierarchy.json` layer to complete the chain. Repair is
capability-driven:

- Datasets with explicit branch identity metadata are repaired only when the
  candidate belongs to the same branch/path as the polygon evidence.
- Older datasets without branch identity metadata remain supported through the
  guarded legacy repair path.
- Name-based fallback is only used when no branch evidence can be established
  and the name resolves to exactly one feature in the dataset.

Cadis does not mutate datasets during repair. Invalid or cross-branch repair
candidates are rejected instead of overriding polygon-derived evidence.

## Architecture

```text
cadis (public control layer)
  -> world resolution (`cadis.world`)
  -> dataset install/provisioning (`cadis.cdn`)
  -> dataset bootstrap/lookup runtime (`cadis.runtime`)
  -> deterministic structural engine (`cadis.core`)
  -> remote REST surface (`cadisd`)
```

## ISO Code Policy

Cadis uses ISO 3166-1 alpha-2 codes as technical identifiers.

These codes are interpreted strictly according to the ISO 3166 standard and are used solely for data partitioning and administrative dataset selection.

Cadis does not interpret ISO codes as political statements or sovereignty declarations.

---

## Supported ISO 3166-1 Entities

| ISO2 | Name | Dataset ID | Package Size (tar.gz) | Unpacked Size | Release Date (UTC) |
|:-----|:-----|:-----------|----------------------:|--------------:|-------------------:|
| TW | Taiwan | tw.admin | 1.8 MB | 2.0 MB | 2026-04-05 |
| JP | Japan | jp.admin | 20.4 MB | 21.4 MB | 2026-04-05 |
| GB | United Kingdom | gb.admin | 4.8 MB | 5.2 MB | 2026-04-05 |
| IT | Italy | it.admin | 22.9 MB | 26.0 MB | 2026-04-05 |
| KR | South Korea | kr.admin | 2.4 MB | 3.5 MB | 2026-04-05 |
| SE | Sweden | se.admin | 0.2 MB | 0.3 MB | 2026-04-05 |
| NO | Norway | no.admin | 0.1 MB | 0.3 MB | 2026-04-05 |
| DK | Denmark | dk.admin | 0.1 MB | 0.2 MB | 2026-04-05 |
| BE | Belgium | be.admin | 2.7 MB | 2.9 MB | 2026-04-03 |
| NL | Netherlands | nl.admin | 2.6 MB | 2.8 MB | 2026-04-11 |
| FR | France | fr.admin | 24.3 MB | 37.9 MB | 2026-04-29 |
| DE | Germany | de.admin | 26.4 MB | 30.6 MB | 2026-04-27 |
| ES | Spain | es.admin | 11.3 MB | 14.7 MB | 2026-04-27 |
| PT | Portugal | pt.admin | 5.8 MB | 7.2 MB | 2026-04-27 |
| FI | Finland | fi.admin | 0.9 MB | 1.1 MB | 2026-04-27 |
| US | United States of America | us.admin | 31.4 MB | 43.5 MB | 2026-04-27 |
| CA | Canada | ca.admin | 10.7 MB | 14.0 MB | 2026-04-27 |
| AU | Australia | au.admin | 23.7 MB | 30.2 MB | 2026-04-28 |
| NZ | New Zealand | nz.admin | 0.2 MB | 0.2 MB | 2026-04-28 |
| IS | Iceland | is.admin | 0.1 MB | 0.2 MB | 2026-04-28 |
| CH | Switzerland | ch.admin | 3.9 MB | 4.8 MB | 2026-04-29 |
| AT | Austria | at.admin | 7.0 MB | 7.8 MB | 2026-04-29 |
| PL | Poland | pl.admin | 11.4 MB | 12.7 MB | 2026-04-29 |
| LU | Luxembourg | lu.admin | 0.6 MB | 0.8 MB | 2026-04-29 |
| CZ | Czech Republic | cz.admin | 20.8 MB | 23.7 MB | 2026-04-29 |
| SG | Singapore | sg.admin | 0.01 MB | 0.02 MB | 2026-04-29 |
| MY | Malaysia | my.admin | 0.3 MB | 0.5 MB | 2026-04-29 |
| TH | Thailand | th.admin | 1.3 MB | 2.3 MB | 2026-04-29 |
| ID | Indonesia | id.admin | 6.9 MB | 10.4 MB | 2026-04-30 |
| GR | Greece | gr.admin | 2.5 MB | 3.2 MB | 2026-05-10 |
| TR | Turkey | tr.admin | 11.7 MB | 17.4 MB | 2026-05-10 |
| BR | Brazil | br.admin | 32.2 MB | 37.7 MB | 2026-05-10 |
| IN | India | in.admin | 33.3 MB | 57.4 MB | 2026-05-10 |
| MX | Mexico | mx.admin | 1.6 MB | 2.6 MB | 2026-05-10 |
| PH | Philippines | ph.admin | 2.2 MB | 3.5 MB | 2026-05-10 |
| VN | Vietnam | vn.admin | 0.6 MB | 1.9 MB | 2026-05-10 |
| AR | Argentina | ar.admin | 0.6 MB | 1.6 MB | 2026-05-10 |
| CL | Chile | cl.admin | 0.6 MB | 1.0 MB | 2026-05-11 |
| CO | Colombia | co.admin | 1.0 MB | 2.6 MB | 2026-05-11 |
| PE | Peru | pe.admin | 1.2 MB | 2.0 MB | 2026-05-11 |
| AL | Albania | al.admin | 0.7 MB | 0.9 MB | 2026-05-11 |
| BA | Bosnia and Herzegovina | ba.admin | 0.5 MB | 0.7 MB | 2026-05-11 |
| BG | Bulgaria | bg.admin | 6.2 MB | 7.2 MB | 2026-05-11 |
| HR | Croatia | hr.admin | 8.1 MB | 11.0 MB | 2026-05-11 |
| EE | Estonia | ee.admin | 6.2 MB | 8.1 MB | 2026-05-11 |
| HU | Hungary | hu.admin | 2.1 MB | 3.4 MB | 2026-05-11 |
| LV | Latvia | lv.admin | 1.1 MB | 1.8 MB | 2026-05-11 |
| LT | Lithuania | lt.admin | 2.1 MB | 4.2 MB | 2026-05-11 |
| MC | Monaco | mc.admin | 0.01 MB | 0.01 MB | 2026-05-11 |
| ME | Montenegro | me.admin | 0.1 MB | 0.2 MB | 2026-05-11 |
| RO | Romania | ro.admin | 6.3 MB | 7.6 MB | 2026-05-11 |
| RS | Serbia | rs.admin | 17.8 MB | 20.2 MB | 2026-05-11 |
| SK | Slovakia | sk.admin | 10.5 MB | 13.3 MB | 2026-05-11 |
| SI | Slovenia | si.admin | 0.2 MB | 0.3 MB | 2026-05-11 |
| CY | Cyprus | cy.admin | 1.3 MB | 1.5 MB | 2026-05-11 |
| GE | Georgia | ge.admin | 0.2 MB | 0.4 MB | 2026-05-11 |
| XK | Kosovo | xk.admin | 0.3 MB | 0.4 MB | 2026-05-11 |
| MK | Macedonia | mk.admin | 1.7 MB | 2.5 MB | 2026-05-11 |
| MD | Moldova | md.admin | 2.8 MB | 3.9 MB | 2026-05-11 |
| UA | Ukraine | ua.admin | 5.3 MB | 9.6 MB | 2026-05-11 |
| BO | Bolivia | bo.admin | 1.0 MB | 1.3 MB | 2026-05-11 |
| EC | Ecuador | ec.admin | 0.8 MB | 1.3 MB | 2026-05-11 |
| GY | Guyana | gy.admin | 0.1 MB | 0.2 MB | 2026-05-11 |
| PY | Paraguay | py.admin | 0.5 MB | 0.8 MB | 2026-05-11 |
| SR | Suriname | sr.admin | 0.03 MB | 0.1 MB | 2026-05-11 |
| UY | Uruguay | uy.admin | 0.1 MB | 0.4 MB | 2026-05-11 |
| VE | Venezuela | ve.admin | 1.7 MB | 3.2 MB | 2026-05-11 |
| BS | Bahamas | bs.admin | 0.01 MB | 0.02 MB | 2026-05-11 |
| BZ | Belize | bz.admin | 0.04 MB | 0.1 MB | 2026-05-11 |
| CR | Costa Rica | cr.admin | 0.4 MB | 0.8 MB | 2026-05-11 |
| CU | Cuba | cu.admin | 0.3 MB | 0.5 MB | 2026-05-11 |
| SV | El Salvador | sv.admin | 0.1 MB | 0.3 MB | 2026-05-11 |
| GT | Guatemala | gt.admin | 0.1 MB | 0.2 MB | 2026-05-11 |
| HT | Haiti | ht.admin | 0.6 MB | 0.9 MB | 2026-05-11 |
| DO | Dominican Republic | do.admin | 0.1 MB | 0.1 MB | 2026-05-11 |
| HN | Honduras | hn.admin | 0.2 MB | 0.5 MB | 2026-05-11 |
| JM | Jamaica | jm.admin | 0.04 MB | 0.05 MB | 2026-05-11 |
| NI | Nicaragua | ni.admin | 1.2 MB | 3.6 MB | 2026-05-11 |
| PA | Panama | pa.admin | 0.4 MB | 0.9 MB | 2026-05-11 |
| AF | Afghanistan | af.admin | 0.2 MB | 0.5 MB | 2026-05-11 |
| AM | Armenia | am.admin | 0.1 MB | 0.2 MB | 2026-05-11 |
| AZ | Azerbaijan | az.admin | 0.1 MB | 0.1 MB | 2026-05-11 |
| BD | Bangladesh | bd.admin | 0.5 MB | 1.1 MB | 2026-05-11 |
| BT | Bhutan | bt.admin | 0.2 MB | 0.7 MB | 2026-05-11 |
| KH | Cambodia | kh.admin | 0.2 MB | 0.3 MB | 2026-05-11 |
| TL | Timor-Leste | tl.admin | 0.03 MB | 0.1 MB | 2026-05-11 |
| BH | Bahrain | bh.admin | 0.01 MB | 0.2 MB | 2026-05-11 |
| KW | Kuwait | kw.admin | 0.1 MB | 0.8 MB | 2026-05-11 |
| OM | Oman | om.admin | 0.1 MB | 0.4 MB | 2026-05-11 |
| QA | Qatar | qa.admin | 0.02 MB | 0.2 MB | 2026-05-11 |
| SA | Saudi Arabia | sa.admin | 0.5 MB | 1.8 MB | 2026-05-11 |
| AE | United Arab Emirates | ae.admin | 0.1 MB | 0.5 MB | 2026-05-11 |
| IR | Iran | ir.admin | 2.0 MB | 6.3 MB | 2026-05-11 |
| IQ | Iraq | iq.admin | 0.3 MB | 1.1 MB | 2026-05-11 |
| IL | Israel | il.admin | 0.1 MB | 0.4 MB | 2026-05-11 |
| PS | Palestine | ps.admin | 0.1 MB | 0.2 MB | 2026-05-11 |
| JO | Jordan | jo.admin | 0.04 MB | 0.1 MB | 2026-05-11 |
| KZ | Kazakhstan | kz.admin | 0.6 MB | 1.2 MB | 2026-05-11 |
| KG | Kyrgyzstan | kg.admin | 0.1 MB | 0.2 MB | 2026-05-11 |
| LA | Laos | la.admin | 0.1 MB | 0.2 MB | 2026-05-11 |
| LB | Lebanon | lb.admin | 0.2 MB | 0.6 MB | 2026-05-11 |
| BN | Brunei | bn.admin | 0.05 MB | 0.3 MB | 2026-05-11 |
| MV | Maldives | mv.admin | 0.01 MB | 0.02 MB | 2026-05-11 |
| MN | Mongolia | mn.admin | 0.1 MB | 0.3 MB | 2026-05-11 |
| MM | Myanmar | mm.admin | 0.8 MB | 2.1 MB | 2026-05-11 |
| NP | Nepal | np.admin | 1.6 MB | 4.6 MB | 2026-05-11 |
| KP | North Korea | kp.admin | 0.2 MB | 0.3 MB | 2026-05-11 |
| PK | Pakistan | pk.admin | 0.7 MB | 1.1 MB | 2026-05-11 |
| LK | Sri Lanka | lk.admin | 0.04 MB | 0.2 MB | 2026-05-11 |
| SY | Syria | sy.admin | 0.1 MB | 0.4 MB | 2026-05-11 |
| TJ | Tajikistan | tj.admin | 0.1 MB | 0.2 MB | 2026-05-11 |
| TM | Turkmenistan | tm.admin | 0.04 MB | 0.1 MB | 2026-05-11 |
| UZ | Uzbekistan | uz.admin | 0.2 MB | 0.4 MB | 2026-05-11 |
| YE | Yemen | ye.admin | 0.1 MB | 0.3 MB | 2026-05-11 |
| DZ | Algeria | dz.admin | 1.0 MB | 1.9 MB | 2026-05-11 |
| AO | Angola | ao.admin | 0.1 MB | 0.1 MB | 2026-05-11 |
| BJ | Benin | bj.admin | 0.04 MB | 0.1 MB | 2026-05-11 |
| BW | Botswana | bw.admin | 0.01 MB | 0.02 MB | 2026-05-11 |
| BF | Burkina Faso | bf.admin | 0.1 MB | 0.2 MB | 2026-05-11 |
| BI | Burundi | bi.admin | 0.02 MB | 0.04 MB | 2026-05-11 |
| CM | Cameroon | cm.admin | 0.4 MB | 0.6 MB | 2026-05-11 |
| CV | Cape Verde | cv.admin | 0.02 MB | 0.1 MB | 2026-05-11 |
| CF | Central African Republic | cf.admin | 0.02 MB | 0.1 MB | 2026-05-11 |
| TD | Chad | td.admin | 0.02 MB | 0.1 MB | 2026-05-11 |
| KM | Comoros | km.admin | 0.02 MB | 0.05 MB | 2026-05-11 |
| CG | Congo | cg.admin | 0.1 MB | 0.1 MB | 2026-05-11 |
| CD | Democratic Republic of the Congo | cd.admin | 0.5 MB | 1.2 MB | 2026-05-11 |
| DJ | Djibouti | dj.admin | 0.01 MB | 0.02 MB | 2026-05-11 |
| EG | Egypt | eg.admin | 0.01 MB | 0.05 MB | 2026-05-11 |
| GQ | Equatorial Guinea | gq.admin | 0.03 MB | 0.1 MB | 2026-05-11 |
| ER | Eritrea | er.admin | 0.01 MB | 0.01 MB | 2026-05-11 |
| ET | Ethiopia | et.admin | 0.1 MB | 0.1 MB | 2026-05-11 |
| GA | Gabon | ga.admin | 0.1 MB | 0.1 MB | 2026-05-11 |
| GH | Ghana | gh.admin | 0.2 MB | 0.4 MB | 2026-05-11 |
| GN | Guinea | gn.admin | 0.1 MB | 0.3 MB | 2026-05-11 |
| GW | Guinea-Bissau | gw.admin | 0.03 MB | 0.1 MB | 2026-05-11 |
| CI | Ivory Coast | ci.admin | 0.1 MB | 0.2 MB | 2026-05-11 |
| KE | Kenya | ke.admin | 0.6 MB | 1.3 MB | 2026-05-11 |
| LS | Lesotho | ls.admin | 0.02 MB | 0.03 MB | 2026-05-11 |
| LR | Liberia | lr.admin | 0.1 MB | 0.2 MB | 2026-05-11 |
| LY | Libya | ly.admin | 0.01 MB | 0.02 MB | 2026-05-11 |
| MG | Madagascar | mg.admin | 0.5 MB | 1.0 MB | 2026-05-11 |
| MW | Malawi | mw.admin | 0.03 MB | 0.1 MB | 2026-05-11 |
| ML | Mali | ml.admin | 0.1 MB | 0.1 MB | 2026-05-11 |
| MR | Mauritania | mr.admin | 0.01 MB | 0.02 MB | 2026-05-11 |
| MU | Mauritius | mu.admin | 0.04 MB | 0.2 MB | 2026-05-11 |
| MA | Morocco | ma.admin | 1.1 MB | 2.3 MB | 2026-05-11 |
| MZ | Mozambique | mz.admin | 0.3 MB | 0.5 MB | 2026-05-11 |
| NA | Namibia | na.admin | 0.02 MB | 0.2 MB | 2026-05-11 |
| NE | Niger | ne.admin | 0.04 MB | 0.1 MB | 2026-05-11 |
| NG | Nigeria | ng.admin | 0.8 MB | 2.1 MB | 2026-05-11 |
| RW | Rwanda | rw.admin | 0.1 MB | 0.3 MB | 2026-05-11 |
| SH | Saint Helena, Ascension, and Tristan da Cunha | sh.admin | 0.00 MB | 0.01 MB | 2026-05-11 |
| ST | Sao Tome and Principe | st.admin | 0.01 MB | 0.03 MB | 2026-05-11 |
| SN | Senegal | sn.admin | 0.2 MB | 0.6 MB | 2026-05-11 |
| GM | Gambia | gm.admin | 0.02 MB | 0.1 MB | 2026-05-11 |
| SC | Seychelles | sc.admin | 0.01 MB | 0.04 MB | 2026-05-11 |
| SL | Sierra Leone | sl.admin | 0.04 MB | 0.1 MB | 2026-05-11 |
| SO | Somalia | so.admin | 0.03 MB | 0.1 MB | 2026-05-11 |
| ZA | South Africa | za.admin | 1.6 MB | 3.4 MB | 2026-05-11 |
| SS | South Sudan | ss.admin | 0.1 MB | 0.1 MB | 2026-05-11 |
| SD | Sudan | sd.admin | 0.1 MB | 0.2 MB | 2026-05-11 |
| SZ | Eswatini | sz.admin | 0.02 MB | 0.05 MB | 2026-05-11 |
| TZ | Tanzania | tz.admin | 0.2 MB | 0.5 MB | 2026-05-11 |
| TG | Togo | tg.admin | 0.03 MB | 0.1 MB | 2026-05-11 |
| TN | Tunisia | tn.admin | 0.5 MB | 1.5 MB | 2026-05-11 |
| UG | Uganda | ug.admin | 0.1 MB | 0.7 MB | 2026-05-11 |
| ZM | Zambia | zm.admin | 0.1 MB | 0.2 MB | 2026-05-11 |
| ZW | Zimbabwe | zw.admin | 0.1 MB | 0.2 MB | 2026-05-11 |
| CN | China | cn.admin | 14.2 MB | 26.9 MB | 2026-05-12 |
| HK | Hong Kong | hk.admin | 0.01 MB | 0.04 MB | 2026-05-12 |
| MO | Macau | mo.admin | 0.00 MB | 0.00 MB | 2026-05-12 |

Additional ISO 3166-1 entity datasets will be published as they become available.

The `us.admin` dataset also covers supported U.S. territory extracts in the published source set. Cadis routes Puerto Rico (`PR`) and U.S. Virgin Islands (`VI`) lookups through the `US` dataset package.

## License

Cadis source code is licensed under Apache License 2.0. See [`LICENSE`](LICENSE).

The bundled file [`cadis/world/data/ne.global.v0.1.0.cgd`](cadis/world/data/ne.global.v0.1.0.cgd) is transformed from Natural Earth data. Natural Earth states that its raster and vector data on the site are public domain and that no permission is needed to use it. See [`cadis/world/data/CGD_SPEC.md`](cadis/world/data/CGD_SPEC.md) and [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
