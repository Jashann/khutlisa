# Running Khutlisa as a public demonstration on Google Cloud

Live at **https://35-222-83-164.sslip.io** since 13 November 2026, on the Google Cloud VM `khutlisa-demo`
(us-central1-a), until it stops itself on 22 November 2026. "What was run" below is the record.

What runs: one container with the Python server, the built web app, whisper.cpp and ffmpeg for voice, and the
fonts for letters. A second, stock container (Caddy) sits in front of it for HTTPS. The data lives on a
persistent disk mounted at `/data`, not in the image.

## What was checked

| Item | Result, 13 November 2026 |
| --- | --- |
| The image build (`docker build`) | Built on the VM (Docker 29.9.3) on the first attempt: 1.37 GB. |
| The image's test entrypoint (`docker run --rm khutlisa test`) | "Every required check passed." |
| whisper.cpp tag `v1.7.6`, the `fonts-wqy-zenhei` font path, the uv image | The tag exists and builds `whisper-cli`; the font is found at `/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc`; the uv image is now pinned to `0.12.13` instead of `latest`. |
| The certificate | Let's Encrypt issued it to Caddy over TLS-ALPN on port 443 within five seconds of the first start. Port 80 stays closed. |
| `/api/health`, `/api/ready` | 200 and 200 from outside: California's and Queensland's files loaded, speech on whisper.cpp, Airwallex sandbox keys present, recorded model answers loaded. |
| The walk-through from outside | `WALK_BASE=https://35-222-83-164.sslip.io node scripts/walkthrough.mjs`; screenshots in `docs/shots/live/`. See "What was run". |
| The addresses of California's four zip files | Not needed: the database built on the development machine was copied to the data disk. |
| The model names the API is called with (`src/khutlisa/llm.py`, `_API_MODELS`) | Not exercised: the public copy has no key and replays recorded answers. |

## Configuration: environment variables only

No credential is in the image, in this folder or in the compose file. Secrets are in one file on the VM,
`/etc/khutlisa/khutlisa.env` (mode 600), read by Docker at start. `khutlisa.env.example` is the template.

| Variable | What it does |
| --- | --- |
| `KHUTLISA_PUBLIC_DEMO=1` | Public demonstration mode (below). Set by the compose file. |
| `KHUTLISA_PAYER_KEY` | The key to the holder's view. In public demonstration mode it is given to every visitor's page on purpose, so use a value that is used nowhere else. |
| `KHUTLISA_ID_SECRET` | Keeps the ids of register rows the same across restarts. Any long random text. |
| `ANTHROPIC_API_KEY` | The language model. See "The language model". |
| `AWX_CLIENT_ID`, `AWX_API_KEY` | Airwallex **sandbox** keys for the demonstration payments. |
| `KHUTLISA_PUBLIC_URL` | The address owners are sent to in a notice. Set by the compose file from `KHUTLISA_HOST`. |
| `KHUTLISA_TRUSTED_PROXY=1` | Count requests by the address Caddy passes on. Set by the compose file. Never set it on a copy that can be reached without the proxy. |
| `KHUTLISA_MODEL_CALLS_PER_DAY` | The daily budget of model calls in public demonstration mode. Default 150. |
| `KHUTLISA_REQUESTS_PER_MINUTE`, `KHUTLISA_REQUESTS_PER_HOUR` | Per-client limits on every API request in public demonstration mode. Defaults 240 and 3000. |
| `KHUTLISA_SEARCHES_PER_MINUTE`, `KHUTLISA_SEARCHES_PER_HOUR` | Per-client limits on the search itself. Defaults 30 and 300. |
| `KHUTLISA_REGISTER_URLS` | The four zip files of California's records, separated by spaces. Optional. |
| `KHUTLISA_FETCH_REGISTER=0`, `KHUTLISA_FETCH_SPEECH_MODEL=0`, `KHUTLISA_KEEP_ZIPS=1` | Switches for the first start. |
| `KHUTLISA_BOOKS=/data/books.parquet` | The prepared books for the "Book" screens. The image has none at its default path, so set it. |
| `KHUTLISA_HOST` | The public name. Read by the compose file (from `deploy/.env` on the VM), not by the app. |
| `KHUTLISA_DB`, `KHUTLISA_TOTALS`, `KHUTLISA_CLAIMS`, `KHUTLISA_WHISPER_MODEL`, `KHUTLISA_WIDE_FONT`, `PORT` | Paths inside the container, set in the Dockerfile. Leave them alone. |

## Public demonstration mode

With `KHUTLISA_PUBLIC_DEMO=1` the copy keeps the real search over California's file, the "who is owed" and
holders screens, the demonstration journeys (Marisol and Amihan, and the invented holder file) and the
Airwallex sandbox payments. It closes everything a stranger could misuse (`src/khutlisa/public_demo.py`):

- A claim can be opened only on a demonstration record. Nobody's real details can be attached to a real record.
- Only the sample documents that ship with the product are accepted. Any other upload is refused.
- Only the demonstration sound files are transcribed. A visitor's own recording is refused; typing still works.
- Only the invented holder file can be loaded as a holder's list.
- A payment can be planned, approved or started only on a demonstration claim.
- The language model's answers for the demonstration inputs are replayed from a recording (below). With a key,
  other calls are allowed up to a small number a day; when that budget is used, the screens say: "Today's small
  budget of language model calls for this public demonstration is used up."
- Payment explanations use their fixed sentences, and funding on Metal is off (below).
- Every API request is counted per client address, per minute and per hour.
- A line at the foot of every screen says that it is a public demonstration and that nothing real should be typed.

Health and readiness: `/api/health` answers as soon as the process is up. `/api/ready` answers 200 once
California's file is loaded and the pages are built, and 503 with the build's progress until then.

## The language model

In development the app hands model calls to the `claude` program installed on the machine. That program is not
in the container, and the public copy has no `ANTHROPIC_API_KEY`: nobody pays for model calls there.

**Recorded answers.** In public demonstration mode only fixed inputs are accepted anyway: the demonstration
sound files, the sample documents, the invented holder file and the demonstration people's own words. For each
of them the model was asked once, on the development machine, and its answer ships in
`src/khutlisa/recorded_answers.json`, keyed by a hash of the exact prompt and the file bytes
(`src/khutlisa/recorded.py`, `llm.input_key`). In public demonstration mode a call whose key is in that file gets
the recorded answer and does not count against the daily budget. A document is read twice; both readings were
recorded, and the two calls get them in turn, so the comparison of the two readings still runs.

```sh
uv run python scripts/record_demo_answers.py                    # record what is missing (calls the model)
uv run python scripts/record_demo_answers.py --heard-from https://35-222-83-164.sslip.io
                                                                # also cover the words the public copy's
                                                                # recogniser hears in each sound file
uv run pytest -q tests/test_recorded_answers.py                 # every demonstration call has an answer
```

Recorded on 13 November 2026: 34 inputs, 56 answers (Marisol's two versions of her account, as prepared and as
heard, each with both versions of her answer; Amihan's account and answer; both readings of the 11 sample
documents of the two journeys and of the 11 estate documents; the estate family and its one follow-up; the
invented holder file's column mapping as CSV and as a workbook). Every pair of readings agrees. The public copy's
recogniser hears the two sound files exactly as `web/public/demo/heard.json` says.

Any other call takes the path it always took. With no key and no `claude` program it is refused with a sentence
on the screen: "This public demonstration has no live language model. Its answers were recorded in advance for
the demonstration people's words and documents only, and this is not one of them." So:

- A visitor's own typed history or recording is not turned into a search; the form still works.
- A document is stored and not read (and only the sample documents can be uploaded at all).
- The holder's column mapping for the invented file comes from the recording; any other file is refused.
- Notices use the translations that ship with the product (every language is shipped and current, so no call).
- The payment explanations use their fixed sentences in public demonstration mode, with or without a key.

A copy with `ANTHROPIC_API_KEY` replays the recorded answers first and calls the model live for anything else,
within the daily budget. Calls are made for: reading a spoken or typed history (one call), reading a document (two
calls, made at the same time), proposing a holder's column mapping (one call), rewording a payment explanation
(one call, never in public demonstration mode), and a notice translation only when a shipped one is out of date.

## Metal in the public copy: off

Funding on Metal is switched off in public demonstration mode (`metal_api.connect`), and the Metal panel and
`GET /api/metal` say why. Every approval on the public copy is a click by any visitor. On Metal it would be signed
with the demonstration holder's own testnet key, and each pull spends the holder's faucet balance (100 \*USDZ,
about five demonstration claims at the scale of 100) and the prepaid testnet RPC credit, so a few visitors would
use them up for everyone after them; the keys would also have to sit on an internet-facing machine that any
visitor can make sign. The image carries no Node runtime or Metal command line, and no Metal key was copied to
the VM. The Metal runs are recorded in `docs/METAL_RUN_LOG.md`; a copy on a developer's machine with
`scripts/metal_setup.py` done funds claims on Metal.

## Build and test locally

```sh
docker info                                   # stop here if the daemon is not running
docker build -t khutlisa .                    # from the repository root
docker run --rm khutlisa test                 # the image's own checks: no network, no keys, no data
docker run --rm -p 8000:8000 -v khutlisa-data:/data -e KHUTLISA_PAYER_KEY=try-me -e KHUTLISA_FETCH_REGISTER=0 khutlisa
curl -s localhost:8000/api/health             # {"status":"ok"}
curl -s localhost:8000/api/ready              # 503 until California's file is loaded
```

The same checks outside a container: `uv run python deploy/selftest.py`.

## What was run, 13 November 2026

The infrastructure (network `khutlisa-demo-net`, the two firewall rules for 443 and for SSH through IAP only, the
address 35.222.83.164, the VM `khutlisa-demo` with no service account and a fixed stop time of 22 November
23:59 Winnipeg time, the 30 GB data disk with the database, Queensland's register, the books and the speech model
copied onto it) was prepared beforehand with the commands in "Google Cloud: exact commands"; the differences are a
30 GB data disk and an absolute `--termination-time` instead of `--max-run-duration`. Then, from the
development machine:

```sh
gcloud compute instances start khutlisa-demo --zone=us-central1-a
git archive --format=tar.gz -o /tmp/khutlisa-src.tar.gz HEAD          # no data, no claims, no keys
gcloud compute scp /tmp/khutlisa-src.tar.gz khutlisa-demo:~ --zone=us-central1-a --tunnel-through-iap
```

The env file was written on the VM, mode 600, with fresh random values made there and never printed
(`openssl rand -hex`): `KHUTLISA_PUBLIC_DEMO=1`, `KHUTLISA_PAYER_KEY`, `KHUTLISA_ID_SECRET`,
`KHUTLISA_HOST=35-222-83-164.sslip.io`, `KHUTLISA_BOOKS=/data/books.parquet`, `KHUTLISA_FETCH_REGISTER=0`,
`KHUTLISA_FETCH_SPEECH_MODEL=0` and the default limits; the two Airwallex sandbox keys were piped into it from the
development machine's `~/.airwallex_sandbox` over the SSH session, without being printed. No model key and no Metal
key is on the VM. On the VM:

```sh
mkdir -p ~/khutlisa && tar -xzf ~/khutlisa-src.tar.gz -C ~/khutlisa && cd ~/khutlisa
echo KHUTLISA_HOST=35-222-83-164.sslip.io > deploy/.env       # the name the compose file reads
sudo docker build -t khutlisa .                                # built on the first attempt
sudo docker run --rm khutlisa test                             # "Every required check passed."
cd deploy && sudo docker compose up -d                         # Caddy had its certificate 5 seconds later
```

To restart: `cd ~/khutlisa/deploy && sudo docker compose restart` (or `up -d` after a new build). After the VM is
stopped and started again, Docker starts both containers by itself.

**Machine size.** On `e2-standard-2` a search took 19 to 22 seconds warm, so the VM was moved to `e2-standard-4`
(stop, `gcloud compute instances set-machine-type ... --machine-type=e2-standard-4`, start). The search is a scan
of 95 million rows bound by the processor; on 4 shared vCPUs it takes 12 to 15 seconds warm and about 35
seconds for the first search after a start. The development machine does it in about two seconds.

**From outside, from the development machine:**

| Check | Result |
| --- | --- |
| HTTPS | Let's Encrypt certificate for `35-222-83-164.sslip.io`, valid to 11 February 2027; verified by curl |
| `/api/health`, `/api/ready` | 200 and 200; `ready` names the register loaded, speech on whisper.cpp, the Airwallex keys present, 34 recorded inputs |
| Page load (`/`, a fresh browser, three runs) | 0.36 to 0.39 seconds to the load event, the first figure on screen at 0.48 to 0.66 seconds, 494 KB transferred |
| A search over California's and Queensland's files | 12 to 15 seconds (server time), real owners' names masked on every card |
| A typed organisation name in both registers ("telstra") | 4.4 seconds |
| Transcribing a demonstration sound file | 32 to 63 seconds the first time; in public demonstration mode the words of each demonstration file are kept in memory after that, so later visitors wait no longer than the search |
| The walk-through (`WALK_BASE=https://35-222-83-164.sslip.io node scripts/walkthrough.mjs`) | 87 screenshots in `docs/shots/live/`; one timing problem (below) |

What the walk-through did on the public copy, on recorded answers and the Airwallex sandbox:

- Marisol's spoken account (whisper.cpp on the VM heard the same words as on the development machine), her
  follow-up answer lifting her wages record to a strong match, her five documents read twice, proof ready, the
  holder's approval, and her payout with a refused transfer replaced: 2,316.40 US dollars paid as 42,165.85
  Mexican pesos, every currency of Airwallex's ledger at zero. Her 95.00 dollar claim was paid too (1,649.53 MXN).
- Amihan's typed account in Tagalog and her answer, her documents, and her 120.00 dollar claim paid under the fee
  rule as 7,562.85 Philippine pesos, ledger at zero.
- The whole book of Bank of America and a batch of nine invented owners in nine currencies, two refusals
  replaced, every currency at zero.
- The invented holder file: column mapping from the recorded model answer, 3,217 rows, 3,089 usable; notices;
  Marisol answering hers, proven and paid.
- The estate: the family read from the widow's Spanish words, shares 1/3, 2/9, 2/9, 2/9, eleven documents read
  twice, two rounds of settlement in MXN, PHP, GBP and JPY, every currency at zero.

Skipped against the public copy, by design: funding on Metal (off, above); the risk view (its rings are planted
by writing claims into the server's claims folder, and a visitor cannot open claims on real records); the
estate's run log (written from the server's claims folder); and the second server started without the register.

The one problem the walk reported: while Marisol's synthetic voice plays, the words the recogniser heard do not
appear within six seconds, because the first transcription of a file takes most of a minute on this machine.
They appear once it finishes, and the journey goes on.

**Refusals, tried with plain HTTP requests from outside:**

| Attempt | Answer |
| --- | --- |
| Open a claim on a real record from California's file | 403: "This is a public demonstration. A claim can be opened only on a demonstration record, so that nobody's real details are entered here." |
| Upload a document that is not one of the samples, to a demonstration claim | 403: "This is a public demonstration, so only the sample documents offered on this screen can be added." |
| Upload a recording of one's own | 403: "This is a public demonstration, so only the spoken example is transcribed." |
| Upload a holder file of one's own, with the holder's key | 403: "This is a public demonstration, so only the invented holder file can be loaded here." |
| Type one's own history | 503: "This public demonstration has no live language model. Its answers were recorded in advance for the demonstration people's words and documents only, and this is not one of them." |
| Plan or approve a payout for a claim that is not a demonstration claim | No such claim can exist on the public copy, since opening one is refused; the routes answer 404 for an unknown claim, and the refusal for a claim on a real record (403) is covered by `tests/test_public_demo.py` |

The claims made by the first walk-through run were moved aside on the data disk
(`/mnt/disks/khutlisa-data/claims-walk-1-1556`) before the run recorded above, so that it started from an empty
claims folder.

## Google Cloud: exact commands

One small VM, one persistent data disk, one fixed address, a network of its own with two firewall rules. Every
resource that can carry labels carries the same ones. Firewall rules and networks cannot carry labels in Google
Cloud, so they carry the name prefix `khutlisa-demo` and a description.

Set these once in the shell. `STOP_BY` is the day the copy should be gone.

```sh
export PROJECT=your-project-id
export ZONE=us-central1-a
export REGION=us-central1
export NAME=khutlisa-demo
export STOP_BY=2026-11-20
export LABELS="app=khutlisa,purpose=public-demo,owner=your-name,stop-by=${STOP_BY}"
gcloud config set project "$PROJECT"
gcloud services enable compute.googleapis.com
```

### 1. A network that lets in HTTPS only

```sh
gcloud compute networks create "$NAME-net" --subnet-mode=auto \
  --description="Khutlisa public demonstration. Delete after ${STOP_BY}."
gcloud compute firewall-rules create "$NAME-https" --network="$NAME-net" --direction=INGRESS \
  --allow=tcp:443 --source-ranges=0.0.0.0/0 --target-tags="$NAME" \
  --description="Khutlisa public demonstration: HTTPS only. Delete after ${STOP_BY}."
# Administration only: SSH through Google's Identity-Aware Proxy, not from the internet.
gcloud compute firewall-rules create "$NAME-iap-ssh" --network="$NAME-net" --direction=INGRESS \
  --allow=tcp:22 --source-ranges=35.235.240.0/20 --target-tags="$NAME" \
  --description="Khutlisa public demonstration: SSH through IAP only. Delete after ${STOP_BY}."
```

Port 80 stays closed. Caddy proves the certificate over port 443.

### 2. A fixed address, a data disk and the VM

The database is about 5.4 GB once built. The four zip files and the half-built database need room beside it
during the first start, so the data disk is 60 GB.

```sh
gcloud compute addresses create "$NAME-ip" --region="$REGION" --labels="$LABELS"
export IP=$(gcloud compute addresses describe "$NAME-ip" --region="$REGION" --format='value(address)')
export KHUTLISA_HOST="$(echo "$IP" | tr . -).sslip.io"      # or a name of your own that points at $IP

gcloud compute disks create "$NAME-data" --zone="$ZONE" --size=60GB --type=pd-balanced --labels="$LABELS"

gcloud compute instances create "$NAME" --zone="$ZONE" --machine-type=e2-standard-4 \
  --image-family=debian-12 --image-project=debian-cloud --boot-disk-size=30GB --boot-disk-type=pd-balanced \
  --disk="name=$NAME-data,device-name=khutlisa-data,mode=rw,auto-delete=no" \
  --network="$NAME-net" --address="$IP" --tags="$NAME" --labels="$LABELS" \
  --max-run-duration=72h --instance-termination-action=STOP \
  --metadata=enable-oslogin=TRUE
gcloud compute disks add-labels "$NAME" --zone="$ZONE" --labels="$LABELS"      # the boot disk
```

`--max-run-duration=72h --instance-termination-action=STOP` is the automatic stop: Google stops the VM three
days after it starts. A stopped VM costs nothing for its CPU, but its disks and its address still cost a little
until the teardown below is run. If `gcloud` refuses the address label on your version, create the address
without `--labels` and run `gcloud compute addresses update "$NAME-ip" --region="$REGION" --update-labels="$LABELS"`.

### 3. Prepare the VM

```sh
gcloud compute ssh "$NAME" --zone="$ZONE" --tunnel-through-iap
```

On the VM:

```sh
curl -fsSL https://get.docker.com | sudo sh
sudo mkfs.ext4 -m 0 -F /dev/disk/by-id/google-khutlisa-data        # first time only: this erases the data disk
sudo mkdir -p /mnt/disks/khutlisa-data
echo '/dev/disk/by-id/google-khutlisa-data /mnt/disks/khutlisa-data ext4 discard,defaults,nofail 0 2' | sudo tee -a /etc/fstab
sudo mount -a
sudo chown 10001:10001 /mnt/disks/khutlisa-data                    # the user the container runs as
sudo mkdir -p /etc/khutlisa && sudo install -m 600 /dev/null /etc/khutlisa/khutlisa.env
sudo nano /etc/khutlisa/khutlisa.env                               # fill in from deploy/khutlisa.env.example
```

Type the secrets into that file on the VM. Do not put them in instance metadata, in a startup script or on a
command line, where they would be stored or logged.

### 4. Copy the source, build and start

From the workstation, in the repository:

```sh
git archive --format=tar.gz -o /tmp/khutlisa-src.tar.gz HEAD
gcloud compute scp /tmp/khutlisa-src.tar.gz "$NAME":~ --zone="$ZONE" --tunnel-through-iap
echo "$KHUTLISA_HOST"                                              # note it for the next step
```

On the VM:

```sh
mkdir -p ~/khutlisa && tar -xzf ~/khutlisa-src.tar.gz -C ~/khutlisa && cd ~/khutlisa
sudo docker build -t khutlisa .
sudo docker run --rm khutlisa test                                 # must end with "Every required check passed."
cd deploy && sudo KHUTLISA_HOST=<the name noted above> docker compose up -d
sudo docker compose logs -f app                                    # the first start prints its progress
```

Then, from anywhere:

```sh
curl -s "https://$KHUTLISA_HOST/api/health"
curl -s "https://$KHUTLISA_HOST/api/ready"      # 503 with the progress, then 200
```

### 5. Loading California's file

The first start tries to fetch and build the database by itself and reports its progress on `/api/ready` and
in the logs. The server is up meanwhile, on the demonstration records. Three ways, most reliable first:

1. **Copy the database you already have.** On the workstation:
   `gcloud compute scp data/registers.duckdb data/totals.json "$NAME":/tmp/ --zone="$ZONE" --tunnel-through-iap`,
   then on the VM `sudo install -o 10001 -g 10001 /tmp/registers.duckdb /tmp/totals.json /mnt/disks/khutlisa-data/`
   and `sudo docker compose restart app`. About 5.4 GB. Set `KHUTLISA_FETCH_REGISTER=0` in the env file first if
   the automatic fetch should not run at all.
2. **Give the four addresses.** Open https://www.sco.ca.gov/upd_download_property_records.html in a browser, copy
   the links of the four files named `01_From_...` to `04_From_...`, put them in `KHUTLISA_REGISTER_URLS` in the
   env file, and `sudo docker compose up -d`. The download and the build take a while and show their progress.
3. **Leave it to the first start.** With `KHUTLISA_REGISTER_URLS` empty it reads the links from that page. This
   may fail where the page asks for a browser check; the progress then says "failed" with the reason and the
   server stays on the demonstration records.

Building needs memory: use the 16 GB machine type above for the build. If way 1 is used, `e2-standard-2` is
enough to serve, at about half the hourly price, though a search over 95 million records is slower on two cores.

### 6. A managed certificate instead of Caddy

Caddy with Let's Encrypt is the short way and is what the compose file does. The alternative is a Google-managed
certificate on an external HTTPS load balancer in front of the VM. It needs a domain name of your own, an
instance group, a backend service, a URL map, a target HTTPS proxy and a forwarding rule, and it costs about
0.025 US dollars an hour for the forwarding rule on top of the VM. It is not written out here because the
demonstration does not need it.

## Cost estimate

List prices read from the Cloud Billing catalog on 13 November 2026, us-central1, on demand, US dollars.

| Resource | Per hour | Three days (72 h) |
| --- | --- | --- |
| VM `e2-standard-4` (4 vCPU, 16 GB): $0.02181 per vCPU-hour and $0.00292 per GB-hour | $0.134 | $9.65 |
| Data disk 30 GB and boot disk 20 GB, `pd-balanced` ($0.10 per GB a month) | $0.007 | $0.49 |
| Fixed external address, in use | $0.005 | $0.36 |
| **Total while running** | **about $0.146** | **about $10.50** |

The VM in this project runs from 13 November to the automatic stop on 22 November, about 230 hours: about 34
US dollars at most. On `e2-standard-2` it would be about $0.079 an hour, with searches near 20 seconds. Not
included: network egress (about $0.12 per GB; a visit transfers about 0.5 MB of pages). There is no model cost:
the public copy has no key. The Airwallex sandbox is free.

After the automatic stop, the two disks and the address still cost about $0.017 an hour together ($0.40 a day)
until they are deleted.

## Teardown

Run all of it. The automatic stop only stops the VM.

```sh
gcloud compute instances delete "$NAME" --zone="$ZONE" --quiet
gcloud compute disks delete "$NAME-data" --zone="$ZONE" --quiet          # the data disk is kept on VM deletion
gcloud compute addresses delete "$NAME-ip" --region="$REGION" --quiet
gcloud compute firewall-rules delete "$NAME-https" "$NAME-iap-ssh" --quiet
gcloud compute networks delete "$NAME-net" --quiet
```

Check that nothing is left:

```sh
gcloud compute instances list --filter="labels.app=khutlisa"
gcloud compute disks list --filter="labels.app=khutlisa"
gcloud compute addresses list --filter="labels.app=khutlisa"
gcloud compute firewall-rules list --filter="name~^khutlisa-demo"
gcloud compute networks list --filter="name~^khutlisa-demo"
```

Each should print nothing. Then rotate what the copy used: the Anthropic key, the Airwallex sandbox keys and
the holder's key.
