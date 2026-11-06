#!/usr/bin/env bash
# Read-only candidate/runtime drift audit. No Compose up/restart and no secret output.
set -Eeuo pipefail
umask 077

cd /opt/davarna-v2
die() { echo "BLOCKER: $*" >&2; exit 2; }
[[ "$(id -u)" == 0 ]] || die "Run as root; compose config includes production credentials"
[[ "$(git branch --show-current)" == "feature/ui-ux-refresh-tambola-v2-20261106" ]] || die "Unexpected branch"
[[ -z "$(git status --porcelain --untracked-files=no)" ]] || die "Dirty tracked working tree"

BASE=/opt/davarna/docker-compose.yml
INACTIVE=/opt/davarna-v2/deploy/tambola-v2-inactive.compose.yml
MANUAL=/root/davarna-v2-release-backups/tambola-v2-manual.compose.yml
CANDIDATE=/opt/davarna-v2/dev/release/ux5-candidate.compose.yml
ROOT=/opt/davarna
REV=f3c649e22593
RECORD=/root/davarna-v2-release-backups/candidate-ux5-$REV.txt
DAVARNA_UX5_BACKEND_IMAGE=davarna-backend:ux5-$REV
DAVARNA_UX5_BOT_IMAGE=davarna-bot:ux5-$REV
TAMBOLA_V2_BACKEND_IMAGE=$DAVARNA_UX5_BACKEND_IMAGE
TAMBOLA_V2_BOT_IMAGE=$DAVARNA_UX5_BOT_IMAGE
export DAVARNA_UX5_BACKEND_IMAGE DAVARNA_UX5_BOT_IMAGE
export TAMBOLA_V2_BACKEND_IMAGE TAMBOLA_V2_BOT_IMAGE

for path in "$BASE" "$INACTIVE" "$MANUAL" "$CANDIDATE" "$RECORD" "$ROOT/.env.prod"; do
  [[ -f "$path" ]] || die "Required config or candidate record missing: $path"
done
if ! git diff --quiet "$REV" HEAD -- backend/app davarna-bot/bot; then
  die "Application source changed since candidate build; rebuild candidates first"
fi
[[ "$(git rev-parse "$REV")" == "$(grep '^source_commit=' "$RECORD" | cut -d= -f2-)" ]] ||
  die "Candidate record source commit mismatch"
for service in backend bot; do
  if [[ "$service" == backend ]]; then
    image="$DAVARNA_UX5_BACKEND_IMAGE"
  else
    image="$DAVARNA_UX5_BOT_IMAGE"
  fi
  recorded="$(grep "^${service}_candidate_id=" "$RECORD" | cut -d= -f2-)"
  [[ -n "$recorded" && "$(docker image inspect -f '{{.Id}}' "$image")" == "$recorded" ]] ||
    die "Candidate image ID mismatches original validation: $service"
done

[[ "$(docker inspect -f '{{.Config.Image}}' davarna-backend)" == "davarna-backend:v2-937ef711a9db" ]] ||
  die "Backend Production image changed"
[[ "$(docker inspect -f '{{.Config.Image}}' davarna-bot)" == "davarna-bot:v2-937ef711a9db" ]] ||
  die "Bot Production image changed"
for service in backend bot; do
  container="davarna-$service"
  [[ "$(docker inspect -f '{{.State.Running}}' "$container")" == true ]] || die "$container is not running"
  [[ "$(docker inspect -f '{{.State.Health.Status}}' "$container")" == healthy ]] || die "$container is not healthy"
done
[[ "$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.config_files"}}' davarna-backend)" == "$BASE,$INACTIVE,$MANUAL" ]] ||
  die "Backend original Compose chain changed"
[[ "$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.config_files"}}' davarna-bot)" == "$BASE,$INACTIVE" ]] ||
  die "Bot original Compose chain changed"

TMP="$(mktemp -d /root/davarna-ux-audit.XXXXXX)"
cleanup() {
  case "$TMP" in
    /root/davarna-ux-audit.*) [[ ! -d "$TMP" ]] || rm -rf -- "$TMP" ;;
  esac
}
trap cleanup EXIT
chmod 0700 "$TMP"

# The full config JSON contains secrets. Never display it or its command stderr.
echo "===== RENDERING CANDIDATE CONFIG (PRIVATE, READ ONLY) ====="
cd "$ROOT"
if ! docker compose -p davarna --env-file "$ROOT/.env.prod" \
  -f "$BASE" -f "$INACTIVE" -f "$MANUAL" -f "$CANDIDATE" \
  config --format json > "$TMP/backend.json" 2> "$TMP/compose.stderr"; then
  die "Backend Compose config rendering failed; inspect locally without sharing secrets"
fi
if ! docker compose -p davarna --env-file "$ROOT/.env.prod" \
  -f "$BASE" -f "$INACTIVE" -f "$CANDIDATE" \
  config --format json > "$TMP/bot.json" 2> "$TMP/compose.stderr"; then
  die "Bot Compose config rendering failed; inspect locally without sharing secrets"
fi
chmod 0600 "$TMP"/*.json

echo "===== COMPARING EFFECTIVE SERVICE CONFIG (NO SECRET VALUES) ====="
python3 - "$TMP/backend.json" "$TMP/bot.json" <<'PY'
import json
import subprocess
import sys

def load(path):
    with open(path, encoding="utf-8") as fp:
        return json.load(fp)

def inspect(container):
    return json.loads(subprocess.check_output(["docker", "inspect", container], text=True))[0]

def image_config(tag):
    return json.loads(subprocess.check_output(["docker", "image", "inspect", tag], text=True))[0]

def to_env(entries):
    return {x.split("=", 1)[0]: x.split("=", 1)[1] for x in (entries or []) if "=" in x}

def norm_ip(value):
    if str(value or "") in ("", "0.0.0.0", "::"):
        return "0.0.0.0"
    return str(value)

def live_ports(info):
    out = set()
    for key, bindings in (info["HostConfig"].get("PortBindings") or {}).items():
        if not bindings:
            continue
        for bind in bindings:
            out.add((key, norm_ip(bind.get("HostIp")), str(bind.get("HostPort") or "")))
    return out

def target_ports(service):
    out = set()
    for port in service.get("ports") or []:
        if not isinstance(port, dict):
            raise ValueError("Unexpected Compose port type")
        port_num = str(port["target"]) + "/" + str(port.get("protocol") or "tcp")
        out.add((port_num, norm_ip(port.get("host_ip")), str(port["published"])))
    return out

def live_volumes(info):
    return {(x.get("Type"), x.get("Source"), x.get("Destination"), not x.get("RW", True))
            for x in (info.get("Mounts") or [])}

def target_volumes(service):
    return {(x.get("type"), x.get("source"), x.get("target"), bool(x.get("read_only", False)))
            for x in (service.get("volumes") or [])}

def public_flags(env):
    names = ["GAME_TAMBOLA_V2_ENABLED", "GAME_AUTO_DRAW_ENABLED",
             "GAME_AUTOPILOT_RUNTIME_ENABLED", "CRYPTO_PAYMENTS_ENABLED"]
    # Report only explicit switches; not credentials or generic ENV.
    return {key: env.get(key, "<unset>") for key in names}

drift = False
for kind, config_path in [("backend", sys.argv[1]), ("bot", sys.argv[2])]:
    desired = load(config_path)["services"][kind]
    current = inspect("davarna-" + kind)
    candidate_tag = "davarna-" + kind + ":ux5-f3c649e22593"
    print(f"--- {kind} ---")
    if desired.get("image") != candidate_tag:
        print("BLOCKER: candidate image changed by a Compose override")
        drift = True
    inherited = to_env(image_config(candidate_tag)["Config"].get("Env") or [])
    effective = dict(inherited)
    for key, value in (desired.get("environment") or {}).items():
        if value is None:
            effective.pop(key, None)
        else:
            effective[key] = str(value)
    live = to_env(current["Config"].get("Env") or [])
    # Never print values or hashes of credentials, only names and counts.
    differing = sorted(key for key in set(live) | set(effective) if live.get(key) != effective.get(key))
    print("ENV parity:", "OK" if not differing else "DRIFT")
    if differing:
        print("  ENV names with differences: " + ", ".join(differing))
        drift = True
    live_flags = public_flags(live)
    expected_flags = public_flags(effective)
    for key in live_flags:
        a, b = live_flags[key], expected_flags[key]
        print(f"  {key}: {'UNCHANGED' if a == b else 'CHANGED'}")
        if a != b:
            drift = True

    ap = live_ports(current)
    ep = target_ports(desired)
    print("Published ports:", "OK" if ap == ep else "DRIFT")
    if ap != ep:
        print("  Live ports:", sorted(ap))
        print("  Candidate ports:", sorted(ep))
        drift = True
    av = live_volumes(current)
    ev = target_volumes(desired)
    print("Storage mounts:", "OK" if av == ev else "DRIFT")
    if av != ev:
        print("  Count (live/candidate):", len(av), len(ev))
        print("  Mount targets (live/candidate):", sorted(x[2] for x in av), sorted(x[2] for x in ev))
        drift = True

    restart = str(current["HostConfig"]["RestartPolicy"]["Name"])
    if desired.get("restart", restart) != restart:
        print("BLOCKER: restart policy differs")
        drift = True
    if desired.get("privileged", False) != current["HostConfig"].get("Privileged", False):
        print("BLOCKER: privileged security setting differs")
        drift = True
    if desired.get("read_only", False) != current["HostConfig"].get("ReadonlyRootfs", False):
        print("BLOCKER: readonly rootfs setting differs")
        drift = True
    print("Service configuration check complete")

if drift:
    print("===== NO-GO: CONFIG DRIFT DETECTED; DO NOT DEPLOY =====")
    raise SystemExit(2)
print("===== PREDEPLOY CONFIG MATCH: IMAGE-ONLY CHANGE =====")
PY

echo "Candidate config audit has finished; no container was replaced."
