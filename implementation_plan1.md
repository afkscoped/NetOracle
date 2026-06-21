# NetOracle v4.0 — Master Implementation Plan (Updated)

### Industry-Grade 5G Fault Intelligence: Live Open5GS + ML Validation + Research Novelty

> \\\*\\\*Branch:\\\*\\\* `feature/open5gs-live-integration`  
> \\\*\\\*Last Updated:\\\*\\\* 2026-06-20  
> \\\*\\\*Rule:\\\*\\\* No Docker. FastAPI on Windows + Open5GS in WSL2. Every claim must be backed by a log line, DB row, or screenshot.

\---

## BRANCH ANALYSIS SUMMARY

### ✅ Already Merged into main (and pulled into our branch)

|Branch|Status|What it had|
|-|-|-|
|`feature/v3-ui-backend-upgrades`|✅ MERGED|v3 UI, realistic data generation, backend fixes|
|`feature/nithesh-ui`|✅ MERGED|UI work|
|`codex-alerts-hopfield-review`|✅ MERGED|Improved alerts, Hopfield allocation view|
|`feature/update-mixed-scenario-data`|✅ MERGED|Updated mixed.csv (5760 rows, realistic fault scenarios)|

### ⚠️ Feature Branches — Selectively Cherry-Pick (DO NOT MERGE WHOLE BRANCH)

#### `member3/agentic-saferl` — **1 commit**, net −17,833 lines

> ❌ \\\*\\\*DO NOT MERGE\\\*\\\* — this branch DELETED most of the codebase (open5gs\\\_adapter, data\\\_sources, conformal, notears, realtime\\\_engine, proactive\\\_engine, training\\\_pipeline, xai, 75 files total removed). It only adds a more advanced `adaptive\\\_rl.py` with named `SafetyConstraint` dataclass and Lagrangian updates.
>
> \\\*\\\*CHERRY-PICK only:\\\*\\\* The `adaptive\\\_rl.py` improvements (SafetyConstraint class, ACTION\\\_PROFILES dict, violation\\\_rate tracking).

#### `feature/ai\\\_ml` — **already almost identical to main**

> The diff shows mostly deletions (old scratch files, test files). The `ctgnn\\\_t4\\\_best.pt` artifact is \\\*\\\*12x larger (517KB vs 42KB)\\\*\\\* — this is a significantly better trained model.
> \\\*\\\*CHERRY-PICK:\\\*\\\* `artifacts/ctgnn\\\_t4\\\_best.pt` (better trained model)

#### `feature/member-1-infra` — **already almost identical to main**

> Net −17,833 lines — same pattern as agentic-saferl. DO NOT MERGE.

#### `member3/agentic-saferl` unique valuable code:

```python
# SafetyConstraint dataclass with Lagrangian adaptive λ
@dataclass
class SafetyConstraint:
    name: str
    threshold: float
    penalty\\\_init: float = 1.0
    learning\\\_rate: float = 0.05
    \\\_lambda: float = field(init=False)
    
    def update\\\_lambda(self, constraint\\\_value: float):
        violation = constraint\\\_value - self.threshold
        self.\\\_lambda = max(0.0, self.\\\_lambda + self.learning\\\_rate \\\* violation)
    
    def violation\\\_rate(self) -> float: ...
    def penalty(self, value: float) -> float:
        return self.\\\_lambda \\\* max(0.0, value - self.threshold)
```

\---

## CURRENT STATE ON `feature/open5gs-live-integration`

### Commits Made (5 on top of main)

|Commit|Description|
|-|-|
|`6f4a5ef`|feat(ui): conformal interval bar, ACI panel, toast system, source transition alerts|
|`6705b29`|feat(ui): live/simulated source banner, ACI report endpoint, btnTick fix|
|`7219b62`|feat(aci): adaptive conformal inference online update rule|
|`96e2935`|feat: live ingestion hardening - WSL2 sync, fault injection API, traffic gen, verify script, runbook|
|`dd11341`|fix: source tag persistence, assumed metric comments, per-NF partial source|

\---

## PHASE STATUS

### Phase 1: Audit \& Schema Lock ✅ COMPLETE

* \[x] Telemetry pipeline fully audited (PHASE2\_NOTES.md)
* \[x] `database.py` — source field persistence via `metrics\\\_json.\\\_source`
* \[x] `open5gs\\\_adapter.py` — all metric names flagged ASSUMED
* \[x] `open5gs\\\_adapter.py` — per-NF source tagging (live/partial/simulated)
* \[x] `open5gs\\\_adapter.py` — rate-limited fallback warning

### Phase 2: Live Ingestion Hardening ✅ COMPLETE

* \[x] `scripts/wsl\\\_env\\\_sync.sh` — WSL2 IP auto-detect + portproxy
* \[x] `scripts/fault\\\_injection\\\_api.py` — 4 fault types + restore\_all
* \[x] `scripts/generate\\\_realistic\\\_traffic.py` — mixed load generator
* \[x] `scripts/verify\\\_open5gs\\\_integration.py` — hardened pre-flight (exits non-zero)
* \[x] `LIVE\\\_OPS\\\_RUNBOOK.md` — 9-step daily startup

### Phase 3: ML Pipeline — Novel Contributions ✅ COMPLETE

* \[x] `conformal.py` — ACI `update()` rule: `q̂\\\_{t+1} = q̂\\\_t + γ(𝟙(y ∉ C) - α)`
* \[x] `conformal.py` — `save\\\_calibration(live=True)` separate artifact
* \[x] `main.py` — `/api/conformal/report` and `/api/conformal/update` endpoints
* \[ ] **UPGRADE**: Cherry-pick larger CTGNN model from `feature/ai\\\_ml` (517KB vs 42KB)
* \[ ] **UPGRADE**: Add `SafetyConstraint` Lagrangian tracking from `member3/agentic-saferl`
* \[ ] Live NOTEARS validation on real telemetry data
* \[ ] CTGNN inference validation on live metric distributions

### Phase 4: Frontend — Live Data UX ✅ COMPLETE

* \[x] `datasourceBanner` — green glow for LIVE, amber for PARTIAL, gray for SIMULATED
* \[x] `updateSourceBanner()` — toast on source transition (simulated→live, live→simulated)
* \[x] `conformalInterval` — CI bar under fault probability KPI with q̂ label
* \[x] `renderAciPanel()` — ACI metrics table + adaptation history
* \[x] `btnRefreshACI` — loads `/api/conformal/report` into ACI panel
* \[x] `toast()` — real glassmorphic toast system (4 severity levels)
* \[ ] **UPGRADE**: Source-colored telemetry chart series (live=cyan, simulated=muted)
* \[ ] **UPGRADE**: Ablation tab with CTGNN vs heuristic comparison table

### Phase 5: End-to-End Validation \& Evidence 🔨 TODO

* \[ ] Run LIVE\_OPS\_RUNBOOK.md cold-boot sequence, screenshot PASS output
* \[ ] Trigger 4 fault injection scenarios, measure MTTD per type
* \[ ] Run verify\_open5gs\_integration.py against live stack
* \[ ] Save `artifacts/conformal\\\_calibration\\\_live.json` from ACI updates
* \[ ] Ablation table: CTGNN vs heuristic, ACI vs static CP, live vs simulated
* \[ ] Update PHASE2\_NOTES.md with VERIFIED metric name comments

\---

## UPGRADES REQUIRED (Industry-Grade Gaps)

### 🔴 Critical — Must Do Before Demo

|#|Gap|Fix|
|-|-|-|
|G1|CTGNN model is tiny (42KB) — likely undertrained|Cherry-pick 517KB model from feature/ai\_ml: `git checkout feature/ai\\\_ml -- artifacts/ctgnn\\\_t4\\\_best.pt`|
|G2|Conformal predictor calibrated on simulated data only|Run `/api/conformal/update` with resolved fault labels during testing to build live calibration|
|G3|Open5GS Prometheus metric names all ASSUMED|Must validate: `curl http://localhost:9090/api/v1/label/\\\_\\\_name\\\_\\\_/values` and update adapter comments|
|G4|No evidence that CTGNN outperforms heuristic on live data|Build ablation table using `benchmarks.py` after live data collection|

### 🟡 Important — Strengthens Research Novelty

|#|Gap|Fix|
|-|-|-|
|G5|SafetyConstraint Lagrangian updates exist only in deleted branch|Integrate `SafetyConstraint` dataclass into current `adaptive\\\_rl.py`|
|G6|Telemetry chart doesn't distinguish live vs simulated data points|Color-code chart series by source tag|
|G7|No ablation table in UI|Add benchmarks panel comparing CTGNN vs heuristic, ACI vs static CP|
|G8|NOTEARS DAG never run on real data (always correlation fallback)|Collect 600+ live rows per slice, run discover\_slice\_dag, screenshot edges|

### 🟢 Nice to Have

|#|Gap|Fix|
|-|-|-|
|G9|Hopfield allocation not showing fairness metrics clearly|Already improved in codex-alerts-hopfield-review|
|G10|No accuracy\_tracker.py that feeds into ACI|Wire accuracy tracker to call `/api/conformal/update` after each fault resolves|
|G11|tests/ directory has many broken tests after branch merges|Run pytest, fix import errors, add conformal/ACI unit tests|

\---

## IMMEDIATE NEXT STEPS (ordered by impact)

1. **Cherry-pick better CTGNN model:**

```bash
   git checkout feature/ai\\\_ml -- artifacts/ctgnn\\\_t4\\\_best.pt
   git commit -m "feat(ml): import larger CTGNN model from feature/ai\\\_ml (517KB)"
   ```

2. **Upgrade adaptive\_rl.py with SafetyConstraint Lagrangian:**

   * Extract `SafetyConstraint` dataclass from `member3/agentic-saferl:app/services/adaptive\\\_rl.py`
   * Integrate into current `app/services/adaptive\\\_rl.py`
   * Add `/api/saferl/constraints` endpoint to expose violation rates
3. **Source-colored telemetry chart** in `TelemetryChart.update()`:

   * Color each line based on the `source` field of frames
   * Add legend: LIVE (cyan), PARTIAL (amber), SIMULATED (gray)
4. **Ablation panel** in Causal AI tab:

   * POST to `/api/intelligence/benchmark` with CTGNN vs heuristic
   * Display results as a comparison table
5. **Verify Prometheus metric names** when Open5GS is running:

   * Query `GET /api/v1/label/\\\_\\\_name\\\_\\\_/values` to list actual metric names
   * Update all `# ASSUMED` comments in `open5gs\\\_adapter.py` to `# VERIFIED`

\---

## RESEARCH NOVELTY SUMMARY (for paper/resume)

|Contribution|Status|Evidence|
|-|-|-|
|§5.1 NOTEARS federated DAG with per-slice voting|✅ Implemented|`/api/intelligence/dag`|
|§5.2 CausalAttentionGRU temporal fault prediction|✅ Implemented (upgrading model)|`artifacts/ctgnn\\\_t4\\\_best.pt`|
|§6.3 ACI adaptive conformal inference online update|✅ Implemented|`/api/conformal/report`, `conformal.py:update()`|
|§6.4 GraphRAG multi-agent diagnosis with 2-round debate|✅ Implemented|`rag\\\_llm.py`, `/api/diagnosis`|
|§6.5 CMDP-gated safe remediation with Lagrangian constraints|⚠️ Upgrading|`adaptive\\\_rl.py` + SafetyConstraint|
|§6.6 Hopfield network radio resource allocation|✅ Implemented|`wireless.py`, Jain fairness index|
|Live Open5GS integration with source provenance|✅ Implemented|`open5gs\\\_adapter.py`, source banner|





\# Open5GS Setup Guide — From Zero to Live 5G Core for NetOracle



This is a complete, beginner-assumed walkthrough: what Open5GS actually is, whether you need WSL2, and the exact commands to get a running 5G core + simulated radio/UE feeding live data, so that once your NetOracle code is finished, you can just "turn the network on" and start pulling real telemetry.



\---



\## Part 0 — Do you actually need WSL2?



\*\*Short answer: yes, if you're on Windows.\*\* Open5GS is Linux-only software — it's built from C source, installs as `systemd` services, and uses Linux-specific networking (TUN interfaces, iptables). It does not run natively on Windows.



Your three real options, in order of how much your project's existing docs already assume:



| Option | When to use it | Notes |

|---|---|---|

| \*\*WSL2 with Ubuntu 22.04\*\* | You're on Windows 10 (build 19041+) or Windows 11 — this is what your `OPEN5GS\\\_INTEGRATION.md` already assumes | Easiest path, runs alongside NetOracle on the same machine, but networking between WSL2 and Windows needs one extra setup step (covered below) |

| \*\*A native Ubuntu machine/VM (VirtualBox, dual-boot, cloud VM)\*\* | You have a spare Linux box, or want to avoid WSL2 networking quirks entirely | Slightly more setup overhead upfront, but no WSL2↔Windows bridging headaches later — if NetOracle also runs on that same Linux box, you can even skip networking entirely and just use `localhost` |

| \*\*Skip Linux entirely, keep `DATA\\\_SOURCE\\\_MODE=simulated`\*\* | You don't need real data right now | Not what you asked for, but worth remembering this is always a safe fallback if live setup eats more time than expected |



This guide assumes \*\*WSL2 + Ubuntu 22.04\*\*, since that's what your project's integration docs are built around. If you'd rather use a native Ubuntu VM/machine, every command below is identical — you just skip Part 1 (WSL2 install) and Part 6's networking bridge (since NetOracle and Open5GS would either be on the same machine, or you'd just use the VM's real IP directly).



\---



\## Part 1 — Install WSL2 + Ubuntu 22.04 (skip if using native Linux)



Open \*\*PowerShell as Administrator\*\* on Windows:



```powershell

wsl --install -d Ubuntu-22.04

```



This enables WSL2, downloads Ubuntu 22.04, and installs it. Reboot if prompted. On first launch of the Ubuntu app, set a Linux username/password.



Verify you're on WSL2 (not the older WSL1):



```powershell

wsl -l -v

```



You should see `Ubuntu-22.04` with `VERSION` = `2`. If it shows `1`:



```powershell

wsl --set-version Ubuntu-22.04 2

```



\*\*Important networking note (do this now, saves pain later):\*\* Windows 11 22H2+ supports "mirrored" WSL2 networking, which makes `localhost` on Windows automatically reach services running in WSL2 — no IP juggling, no port forwarding. Check your Windows build, and if supported, create/edit `%UserProfile%\\\\.wslconfig`:



```ini

\\\[wsl2]

networkingMode=mirrored

```



Then `wsl --shutdown` from PowerShell and reopen Ubuntu. If this works, every `<WSL\\\_IP>` reference later in this guide becomes just `localhost`. If your Windows build doesn't support it, don't worry — Part 6 covers the manual IP/port-forward approach your existing docs already describe.



From here on, all commands run \*\*inside the Ubuntu WSL2 terminal\*\* unless marked "(Windows)".



\---



\## Part 2 — Install MongoDB (subscriber database)



Open5GS needs MongoDB to store subscriber (SIM) records.



```bash

sudo apt update

sudo apt install -y gnupg curl

curl -fsSL https://pgp.mongodb.com/server-8.0.asc | sudo gpg -o /usr/share/keyrings/mongodb-server-8.0.gpg --dearmor

echo "deb \\\[ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-8.0.gpg] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/8.0 multiverse" | sudo tee /etc/apt/sources.list.d/mongodb-org-8.0.list

sudo apt update

sudo apt install -y mongodb-org

sudo systemctl start mongod

sudo systemctl enable mongod

```



Verify it's running:



```bash

sudo systemctl status mongod

```



\---



\## Part 3 — Install Open5GS



```bash

sudo apt update

sudo apt install -y software-properties-common

sudo add-apt-repository ppa:open5gs/latest

sudo apt update

sudo apt install -y open5gs

```



This installs and auto-starts every 5G SA core network function as a `systemd` service: NRF, SCP, AMF, SMF, UPF, AUSF, UDM, UDR, PCF, NSSF, BSF.



> If `add-apt-repository` fails with a "could not find a distribution template" error (a known PPA tooling quirk on some Ubuntu 22.04 images), fall back to building from source per Open5GS's official guide at `https://open5gs.org/open5gs/docs/guide/02-building-open5gs-from-sources/` — same end result, just compiles locally instead of using the prebuilt package.



\### Install the WebUI (lets you add subscribers visually instead of via raw MongoDB)



```bash

\\# Node.js (required by the WebUI)

sudo apt install -y ca-certificates curl gnupg

sudo mkdir -p /etc/apt/keyrings

curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | sudo gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg

NODE\\\_MAJOR=20

echo "deb \\\[signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node\\\_$NODE\\\_MAJOR.x nodistro main" | sudo tee /etc/apt/sources.list.d/nodesource.list

sudo apt update

sudo apt install -y nodejs



\\# WebUI itself

curl -fsSL https://open5gs.org/open5gs/assets/webui/install | sudo -E bash -

```



The WebUI runs on port \*\*3000\*\* (older docs may say 9999 — current installs default to 3000; check whichever loads).



\---



\## Part 4 — Configure for NetOracle (PLMN, metrics ports)



By default, the AMF/NRF use test PLMN `999/70`. Your project's docs standardize on the international test PLMN `001/01` and specific Prometheus metrics ports per NF — set those now.



\### 4a. Set PLMN to 001/01



Edit `/etc/open5gs/nrf.yaml`:



```bash

sudo nano /etc/open5gs/nrf.yaml

```



Find the `serving` PLMN block and set:

```yaml

nrf:

\&#x20; serving:

\&#x20;   - plmn\\\_id:

\&#x20;       mcc: 001

\&#x20;       mnc: 01

```



Edit `/etc/open5gs/amf.yaml` and set the matching `guami`, `tai`, and `plmn\\\_support` blocks to `mcc: 001`, `mnc: 01` (three separate places in the file — all need to match).



\### 4b. Enable Prometheus metrics per NF



Each NF config needs a `metrics:` block. Edit each file and add/confirm the block with the ports your NetOracle adapter expects:



```bash

sudo nano /etc/open5gs/amf.yaml

```

```yaml

amf:

\&#x20; metrics:

\&#x20;   server:

\&#x20;     - address: 0.0.0.0

\&#x20;       port: 9095

```



Repeat for:

\- `/etc/open5gs/smf.yaml` → port `9096`

\- `/etc/open5gs/upf.yaml` → port `9097`

\- `/etc/open5gs/pcf.yaml` → port `9098`



Use `address: 0.0.0.0` (not `127.0.0.1`) so Prometheus and any external tooling can actually reach it.



\### 4c. Restart everything to apply changes



```bash

sudo systemctl restart open5gs-nrfd open5gs-scpd open5gs-amfd open5gs-smfd open5gs-upfd open5gs-pcfd open5gs-udmd open5gs-udrd open5gs-ausfd open5gs-bsfd open5gs-nssfd

```



\### 4d. Enable IP forwarding + NAT (so UEs get real internet access)



```bash

sudo sysctl -w net.ipv4.ip\\\_forward=1

sudo iptables -t nat -A POSTROUTING -s 10.45.0.0/16 ! -o ogstun -j MASQUERADE

```



If WSL2's firewall (ufw) is active and causing issues:

```bash

sudo ufw status

sudo ufw disable   # only if it's actively blocking and you understand the tradeoff

```



\---



\## Part 5 — Add a test subscriber



Go to the WebUI in a browser (Windows browser works fine, since WSL2 networking forwards localhost by default for HTTP unless something's misconfigured):



```

http://localhost:3000

```



Login: `admin` / `1423` (change this later if you keep the box running long-term).



Click \*\*Subscriber → +\*\* and enter:

\- \*\*IMSI\*\*: `901700000000001` (any valid test IMSI works; keep this consistent — UERANSIM's UE config must match it exactly)

\- \*\*K\*\*: `465B5CE8B199B49FAA5F0A2EE238A6BC`

\- \*\*OPc\*\*: `E8ED289DEBA952E4283B54E88E6183CA`

\- \*\*Slice\*\*: SST `1`

\- Save.



No restart needed — subscriber changes via the WebUI apply immediately.



\---



\## Part 6 — Install and configure UERANSIM (simulated gNB + UE)



UERANSIM simulates the radio side — both the base station (gNB) and the phone (UE) — entirely in software, so you don't need real radio hardware.



```bash

sudo apt install -y make gcc g++ libsctp-dev lksctp-tools iproute2 git

sudo snap install cmake --classic



cd \\\~

git clone https://github.com/aligungr/UERANSIM.git

cd UERANSIM

make

```



This produces `build/nr-gnb` and `build/nr-ue` binaries.



\### Configure the gNB



```bash

nano config/open5gs-gnb.yaml

```



Set `linkIp`, `ngapIp`, and `gtpIp` to your WSL2 machine's IP (run `hostname -I` in WSL2 to get it — if it's the same machine running Open5GS, which it is in this single-box setup, use that same IP for all three). Set `amfConfigs` → address to the same IP, since the AMF is on the same box.



\### Configure the UE



```bash

nano config/open5gs-ue.yaml

```



Set:

\- `supi`: `imsi-901700000000001` (must exactly match the subscriber you created in Part 5)

\- `mcc`: `'001'`, `mnc`: `'01'`

\- `gnbSearchList`: the same WSL2 IP



\---



\## Part 7 — Turn everything on and verify



```bash

cd \\\~/UERANSIM



\\# Start gNB (leave running in this terminal, or background with \\\&)

sudo ./build/nr-gnb -c config/open5gs-gnb.yaml

```



You should see `NG Setup procedure is successful` — that's your gNB successfully registered with the AMF. \*\*If you don't see this, stop here and fix it before continuing\*\* (see Troubleshooting below) — nothing downstream will work without it.



In a \*\*second\*\* WSL2 terminal:



```bash

cd \\\~/UERANSIM

sudo ./build/nr-ue -c config/open5gs-ue.yaml

```



You should see `Connection setup for PDU session\\\[1] is successful` — your simulated phone is now attached to your 5G network and has a real IP address on a new `uesimtun0` interface.



Confirm the interface exists:



```bash

ip addr show uesimtun0

```



\### Generate real traffic through it



```bash

ping -I uesimtun0 8.8.8.8

```



If this responds, real packets are flowing through your full simulated 5G stack: UE → gNB → AMF/SMF/UPF → internet. This is the moment your system has gone from "installed" to "actually working."



\---



\## Part 8 — Install Prometheus (so NetOracle has metrics to scrape)



```bash

sudo apt install -y prometheus prometheus-node-exporter

```



```bash

sudo tee /etc/prometheus/prometheus.yml > /dev/null <<EOF

global:

\&#x20; scrape\\\_interval: 5s

scrape\\\_configs:

\&#x20; - job\\\_name: 'node'

\&#x20;   static\\\_configs:

\&#x20;     - targets: \\\['localhost:9100']

\&#x20; - job\\\_name: 'open5gs-amf'

\&#x20;   static\\\_configs:

\&#x20;     - targets: \\\['localhost:9095']

\&#x20; - job\\\_name: 'open5gs-smf'

\&#x20;   static\\\_configs:

\&#x20;     - targets: \\\['localhost:9096']

\&#x20; - job\\\_name: 'open5gs-upf'

\&#x20;   static\\\_configs:

\&#x20;     - targets: \\\['localhost:9097']

\&#x20; - job\\\_name: 'open5gs-pcf'

\&#x20;   static\\\_configs:

\&#x20;     - targets: \\\['localhost:9098']

EOF



sudo systemctl restart prometheus

sudo systemctl start prometheus-node-exporter

```



Verify each target is actually being scraped:



```bash

curl http://localhost:9090/-/healthy        # Prometheus itself

curl http://localhost:9095/metrics | head    # AMF metrics

curl http://localhost:9096/metrics | head    # SMF metrics

curl http://localhost:9097/metrics | head    # UPF metrics

```



If any of these `curl` commands return nothing or connection refused, that NF's metrics block in Part 4b isn't applied — go back and recheck that config file and restart the corresponding service.



\---



\## Part 9 — Connect NetOracle (on Windows) to this WSL2 stack



Get your WSL2 IP (skip if you set up mirrored networking in Part 1):



```bash

hostname -I

```



In your NetOracle `.env` (on Windows):



```env

DATA\\\_SOURCE\\\_MODE=open5gs

OPEN5GS\\\_PROMETHEUS\\\_URL=http://<WSL\\\_IP\\\_or\\\_localhost>:9090

OPEN5GS\\\_MONGO\\\_URI=mongodb://<WSL\\\_IP\\\_or\\\_localhost>:27017

OPEN5GS\\\_WEBUI\\\_URL=http://<WSL\\\_IP\\\_or\\\_localhost>:3000

OPEN5GS\\\_POLL\\\_INTERVAL\\\_S=5

```



If you didn't set up mirrored networking, and plain `localhost` doesn't reach WSL2 from Windows for these ports, set up explicit port forwarding from \*\*PowerShell as Administrator\*\*:



```powershell

$wslIp = (wsl hostname -I).Trim().Split(" ")\\\[0]

netsh interface portproxy add v4tov4 listenport=9090 listenaddress=127.0.0.1 connectport=9090 connectaddress=$wslIp

netsh interface portproxy add v4tov4 listenport=27017 listenaddress=127.0.0.1 connectport=27017 connectaddress=$wslIp

netsh interface portproxy add v4tov4 listenport=3000 listenaddress=127.0.0.1 connectport=3000 connectaddress=$wslIp

```



Note that `wsl hostname -I` returns a \*\*new\*\* IP every time WSL2 restarts unless you're on mirrored networking — re-run this whenever the IP changes, or just use `localhost` in `.env` and rely on the portproxy rules above to redirect transparently.



Start NetOracle:



```powershell

.venv\\\\Scripts\\\\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

```



Open `http://127.0.0.1:8000`, check the status bar shows `open5gs` mode, and hit `http://127.0.0.1:8000/api/open5gs/health` — it should report all four NFs as reachable.



\---



\## Part 10 — Daily startup / shutdown cheat sheet



Once everything above is configured once, you don't repeat all 9 parts every time — just this:



\*\*Start (WSL2 terminal):\*\*

```bash

sudo systemctl start mongod

sudo systemctl restart open5gs-nrfd open5gs-scpd open5gs-amfd open5gs-smfd open5gs-upfd open5gs-pcfd open5gs-udmd open5gs-udrd open5gs-ausfd open5gs-bsfd open5gs-nssfd

sudo systemctl restart prometheus prometheus-node-exporter

cd \\\~/UERANSIM \\\&\\\& sudo ./build/nr-gnb -c config/open5gs-gnb.yaml \\\&

sleep 3

cd \\\~/UERANSIM \\\&\\\& sudo ./build/nr-ue -c config/open5gs-ue.yaml \\\&

```



\*\*Start (Windows, after the above succeeds):\*\*

```powershell

.venv\\\\Scripts\\\\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

```



\*\*Stop:\*\*

```bash

sudo pkill nr-ue

sudo pkill nr-gnb

sudo systemctl stop open5gs-nrfd open5gs-scpd open5gs-amfd open5gs-smfd open5gs-upfd open5gs-pcfd open5gs-udmd open5gs-udrd open5gs-ausfd open5gs-bsfd open5gs-nssfd

```



\---



\## Troubleshooting



| Symptom | Likely cause / fix |

|---|---|

| `NG Setup procedure` never succeeds in gNB log | AMF not running, or `amfConfigs` IP in `open5gs-gnb.yaml` is wrong/stale, or PLMN mismatch between AMF config and gNB config |

| UE fails to register / "authentication failure" | IMSI/K/OPc in `open5gs-ue.yaml` don't exactly match the subscriber in the WebUI — copy-paste, don't retype |

| `uesimtun0` interface never appears | UE didn't actually reach "PDU session is successful" — check the UE log for the real error, usually a PLMN or APN/DNN mismatch |

| `curl http://localhost:909X/metrics` returns nothing | That NF's `metrics:` block in its yaml config wasn't applied, or service wasn't restarted after editing — re-check Part 4b |

| Windows can't reach WSL2 services at all | Either set up mirrored networking (Part 1) or the `netsh portproxy` rules (Part 9) — plain `localhost` doesn't bridge automatically on older WSL2 networking modes |

| Everything was working, now nothing is, after a reboot | WSL2 IP changed — re-run `hostname -I` and update `.env` or re-run the `netsh portproxy` commands with the new IP |

| `add-apt-repository ppa:open5gs/latest` errors out | Known PPA tooling issue on some Ubuntu 22.04 images — build Open5GS from source instead (Open5GS's official "Building from Sources" guide) |

| NetOracle dashboard still shows `open5gs\\\_simulated` | Prometheus/Mongo genuinely unreachable from NetOracle's perspective — confirm `.env` is correct and re-test each `curl`/connection step above individually before assuming it's a NetOracle bug |



\---



\## What you now have



A fully real, software-defined 5G SA network — AMF, SMF, UPF, PCF and the rest, actual SIM authentication, actual session establishment, actual IP packets flowing through a UPF — running entirely on your machine via WSL2. Once NetOracle's `.env` is pointed at it correctly, every telemetry tick it ingests is reading genuine Prometheus metrics off a genuine (simulated-radio) mobile network, not a synthetic generator. From here, your `OPEN5GS\\\_REALTIME\\\_RUNBOOK.md` and the fault-injection work from your team plan build directly on top of this foundation.

You are working inside the \*\*NetOracle\*\* repository — a FastAPI + PyTorch platform for federated causal fault intelligence on 5G networks (NOTEARS causal discovery, CausalAttentionGRU/CTGNN prediction, split conformal prediction, GraphRAG multi-agent diagnosis, CMDP-gated remediation, Hopfield radio allocation). Full architecture and math are documented in `NetOracle\_Comprehensive\_Documentation.md`, `OPEN5GS\_INTEGRATION.md`, and `OPEN5GS\_REALTIME\_RUNBOOK.md` in this repo — \*\*read all three fully before writing any code.\*\* The system currently runs almost entirely on `DATA\_SOURCE\_MODE=simulated`. There is an `Open5GSAdapter` and supporting docs for connecting to a real Open5GS 5G core + UERANSIM running in WSL2, but it has not been proven to run reliably end-to-end, the ML pipeline has never been validated against real telemetry, and the frontend doesn't make the live-vs-simulated distinction obvious or visually compelling. Your job is to close all three gaps in one continuous effort. Work through the phases below \*\*in order\*\* — each phase produces an artifact the next phase depends on. Do not skip ahead. After each phase, run whatever tests/checks are available and report status before continuing.  Treat this as a real engineering task, not a demo stub: every claim the system makes (e.g., "live data", "fault detected", "90% coverage") must be backed by something you can point to in logs, a database row, or a screenshot — assume a skeptical reviewer will ask "prove it" at every step.  ---  ## PHASE 1 — Audit \& Schema Lock  1. Read every file under `app/services/`, especially `data\_sources.py`, `open5gs\_adapter.py`, `telemetry.py`, `intelligence.py`, `database.py`, and `main.py`'s WebSocket/auto-tick logic. Build a mental (and written, in a new `PHASE2\_NOTES.md`) model of:    - The exact shape of a telemetry tick dict as it flows from adapter → DB → intelligence → WebSocket.    - Every place `DATA\_SOURCE\_MODE` is branched on.    - Exactly which Prometheus metric names `open5gs\_adapter.py` queries, and what PromQL it issues. 2. Do NOT assume the metric names in `OPEN5GS\_INTEGRATION.md`'s "Metric Mapping Reference" table are still accurate — Open5GS metric exporter names vary by version. If you have a way to query a live or documented `/metrics` endpoint, verify against it; otherwise flag every assumed mapping clearly in code comments as `# ASSUMED METRIC NAME — VERIFY AGAINST LIVE /metrics OUTPUT`. 3. Confirm/fix the fallback behavior: when Prometheus/Mongo are unreachable, the system must clearly tag ticks with `source: "open5gs\_simulated"` vs `source: "open5gs\_live"` — if this distinction is fuzzy or missing anywhere in the pipeline, fix it now. This tag must propagate all the way to the WebSocket payload the frontend receives, unmodified.  ## PHASE 2 — Live Ingestion Hardening  Goal: real Open5GS + UERANSIM telemetry flows into NetOracle continuously and survives for hours without falling back to simulation, with a fault-injection control surface for later phases.  1. Write/verify a WSL2 setup flow per `OPEN5GS\_INTEGRATION.md`: Open5GS NFs with Prometheus metrics exporters enabled on ports 9095-9098, Prometheus scraping them plus node\_exporter, MongoDB with at least one test subscriber, UERANSIM gNB + UE. 2. Solve WSL2↔Windows networking deterministically. Prefer: write a small startup script (bash, run from WSL2 or invoked from a PowerShell wrapper) that detects the current WSL2 IP via `hostname -I`, and rewrites the relevant lines of NetOracle's `.env` (`OPEN5GS\_PROMETHEUS\_URL`, `OPEN5GS\_MONGO\_URI`, `OPEN5GS\_WEBUI\_URL`) automatically, rather than relying on a human to paste an IP every reboot. If `.wslconfig` mirrored networking is available (Windows 11 22H2+), document that as the simpler alternative. 3. Build `scripts/generate\_realistic\_traffic.py` (or shell equivalent) that produces varied, sustained load through `uesimtun0`: mixed ping + iperf3 bursts + periodic bulk HTTP downloads + (if feasible with multiple UERANSIM UE configs) simulated multi-UE registration/deregistration churn. This needs to run unattended for at least 30+ minutes to give the ML pipeline enough signal. 4. Build a small FastAPI/Flask control service running in WSL2 (e.g., `scripts/fault\_injection\_api.py`) exposing HTTP endpoints that NetOracle (running on Windows) or a test harness can call remotely to inject and clear faults:    - `POST /inject/upf\_kill` — stop the Open5GS UPF process/service.    - `POST /inject/bandwidth\_throttle` — apply `tc` bandwidth/latency shaping on `uesimtun0` or the relevant interface.    - `POST /inject/gnb\_drop` — kill the UERANSIM gNB process.    - `POST /inject/subscriber\_auth\_failure` — remove/corrupt a subscriber record in MongoDB to trigger AMF auth failures.    - `POST /inject/restore\_all` — revert every injected fault and restart affected services.    Each endpoint should return a JSON ack with a timestamp, so callers can correlate injection time with detection time later. 5. Write `LIVE\_OPS\_RUNBOOK.md`: an exact, copy-pasteable, idiot-proof sequence from cold boot to "NetOracle dashboard shows `source: open5gs\_live` with non-zero AMF/SMF/UPF metrics" in under 5 minutes. Include a troubleshooting section for the most likely failure modes (Prometheus unreachable, Mongo connection refused, WSL2 IP changed, UERANSIM tunnel not established). 6. Write/extend `scripts/verify\_open5gs\_integration.py` into a real pre-flight check: Prometheus reachable, AMF/SMF/UPF metrics present and non-zero, Mongo reachable with ≥1 subscriber, NetOracle `/api/open5gs/health` returns healthy NF status, `/api/telemetry/tick` returns an `open5gs\_live`-tagged frame, and the WebSocket `/ws/telemetry` actually streams live frames (not just connects). This script must exit non-zero with a clear message on any failure — it will be run before every demo/validation session.  ## PHASE 3 — Intelligence Validation on Real Data  Goal: prove the ML/causal pipeline performs meaningfully on real telemetry, and produce an honest, numbers-backed comparison against the simulated baseline.  1. Once Phase 2's traffic generator has been running for 30+ minutes producing a mix of normal and (with fault injection) abnormal conditions, call the existing `/api/training/export-retrain` endpoint to export collected live telemetry to CSV and retrain the CTGNN model on it. Save the resulting checkpoint and calibration artifacts separately from the original simulated-data checkpoint (don't overwrite — you want both for comparison). 2. Re-run the existing ablation benchmark suite (`app/services/benchmarks.py`) — or extend it if it's hardcoded to simulated scenarios — against real, fault-injected Open5GS data. You now have real ground truth fault timestamps from Phase 2's fault-injection API, use them as labels. 3. Produce `benchmarks\_live\_vs\_simulated.json` (or similar) with side-by-side ROC-AUC, false positive rate, and mean-time-to-prediction for: simulated baseline vs. real Open5GS data. If real-data performance is worse (likely — real data is messier and the original calibration was tuned on synthetic distributions), do not hide that. Instead:    - Recompute conformal calibration (`conformal.py`) specifically on real-data calibration samples, and report empirical coverage on a real held-out test set.    - If coverage drifts from the target \~90%, implement the adaptive conformal update already specified mathematically in the docs (§6.3, $\\hat{q}\_{t+1} = \\hat{q}\_t + \\gamma(\\mathbb{I}(y\_t \\notin C\_t(X\_t)) - \\alpha)$) as a real code path, not just leave it as a roadmap item. 4. Sanity-check NOTEARS causal discovery (`notears.py`) against a real injected fault: e.g., trigger `bandwidth\_throttle`, then confirm the discovered causal DAG actually contains an edge chain consistent with `upf\_dropped\_packets\_total → packet\_loss → throughput collapse` (or whatever the real discovered chain is). Log this explicitly — it's strong evidence the causal engine is finding real structure, not noise. 5. If thresholds (fault probability cutoff, conformal α) are clearly miscalibrated against real data distributions, retune them and document the before/after.  ## PHASE 4 — Visualization Upgrade  Goal: make the live system's behavior immediately legible, trustworthy, and visually strong, with explicit proof it's reacting to something real.  1. Add an unmissable live/simulated status indicator to the dashboard — a persistent banner or badge reflecting the `source` field from the WebSocket stream in real time (e.g., green "● LIVE — Open5GS" vs. amber "○ SIMULATED"). This must update reactively, not just on page load. 2. Build a \*\*synchronized fault timeline view\*\*: a shared time-axis visualization showing, for a given incident window: (a) the raw underlying Open5GS metric value over time (e.g., `upf\_dropped\_packets\_total` climbing), (b) NetOracle's predicted fault probability over the same window, (c) the conformal prediction interval band, (d) markers for when an alert fired and when a remediation action was recommended/simulated. This is the centerpiece visual — it should make the causal link between "real network event" and "AI response" visually obvious without narration. 3. Enhance the existing 3D digital twin so that when a real fault is active, the actual affected node (UPF/AMF/SMF/gNB, whichever is really under stress in WSL2) is highlighted/pulsed — not a generic or random node. Wire this directly off the live alert payload, not a hardcoded mapping. 4. Add an \*\*Evidence panel\*\* next to the existing GraphRAG/LLM diagnosis card, showing the raw data trail behind the diagnosis: the actual Prometheus query + returned value, the actual Mongo subscriber state if relevant, and timestamps — so a skeptical viewer can verify the LLM narrative against raw numbers, not just take it on faith. 5. Harden WebSocket reconnect handling in the frontend (silent WS drops are the #1 way live demos visibly break) and add basic loading/error states throughout. 6. Once everything above works against live data, record a 60–90 second screen capture of one full cycle (fault injected → detected → diagnosed → remediation simulated) as a guaranteed fallback artifact in case live networking misbehaves during a real demo.  ## PHASE 5 — End-to-End Validation \& Evidence Report  Goal: produce hard numbers and artifacts proving the full closed loop works on real, externally-verifiable faults — and be explicit about what's still simulated.  1. Build `scripts/live\_fault\_scenarios.py`: an orchestration harness that, for each fault type (UPF kill, bandwidth throttle, gNB drop, subscriber auth failure), calls Phase 2's fault-injection API, then polls NetOracle's `/api/open5gs/health` and `/api/telemetry/tick`/alert endpoints to record: time-to-detection, the diagnosis produced, the recommended action, and whether the CMDP safety filter behaved as expected. Repeat each scenario at least 3 times. Log everything with precise timestamps to structured JSON/CSV. 2. From that harness output, compute and report: mean-time-to-detection (MTTD) per fault type, detection accuracy/false-positive rate on real induced faults, and conformal empirical coverage on the real test set (cross-reference with Phase 3). 3. Write `EVIDENCE\_REPORT.md` containing: the above numbers, the synchronized timeline screenshots from Phase 4, the causal-graph evidence from Phase 3 step 4, and — importantly — an explicit, honest "what's real vs. what's still simulated" section (e.g., remediation actions are evaluated/simulated via `REMEDIATION\_MODE=simulation` rather than executing on real K8s/SDN/RIC control planes — that's a legitimate scope boundary, state it plainly rather than implying full closed-loop automation that doesn't exist). 4. Write a `DEMO\_SCRIPT.md`: an exact, rehearsable sequence of actions and talking points for presenting this live, including the pre-flight check from Phase 2 step 6 as the literal first step, and a documented fallback to the Phase 4 recording if live networking fails mid-demo.  ---  ## Engineering ground rules throughout  - Don't fabricate metric mappings, benchmark numbers, or "proof" — if something can't be verified against a real running system in this environment, clearly mark it as an assumption/TODO rather than presenting it as validated. - Prefer extending existing modules (`open5gs\_adapter.py`, `benchmarks.py`, `conformal.py`, etc.) over creating parallel/duplicate implementations — the codebase already has clean interfaces per the architecture docs, respect them. - Every new script should fail loudly and specifically (not silently fall back to simulated mode without a clear log line) so debugging during integration doesn't turn into guesswork. - Keep `DATA\_SOURCE\_MODE=simulated` fully functional throughout — don't break the existing simulated demo path while building out the live path; they should coexist via the existing strategy-adapter pattern in `data\_sources.py`. - At the end of each phase, summarize what was built, what was verified (with evidence), and what remains uncertain, before moving to the next phase.We r building the Netoracle as I said, I have attached a plan also as well in which some part is done





