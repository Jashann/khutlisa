"""Sets Metal testnet up for Khutlisa, once: keys, funds, an RPC endpoint and the holder's Metal account.

    cd tools/metal && npm install && cd ../..
    uv run python scripts/metal_setup.py

Everything it creates is a testnet key or a testnet address. Key files and the RPC endpoint go under
~/.khutlisa_metal (or KHUTLISA_METAL_HOME) with mode 600 and are never printed; only addresses and transaction
hashes are. It can be run again: each step is skipped when its result is already there.

  agent/key.json            Khutlisa's agent. Buys the RPC endpoint and pays the gas that records a refusal.
  settlement/key.json       Khutlisa's settlement address: the only address a mandate may pay.
  holder/owner-key.json     The holder's owner key. In real use the holder keeps this in its own wallet.
  rpc_url                   The RPC endpoint the agent bought for 1 *USDZ. The URL is its own credential.
  config.json               The public addresses of the above, read by src/khutlisa/metal.py.

The public faucet gives one grant a minute and ten a day to one IP address, each topping an address up to
100 *USDZ. This script asks it three times (agent, holder's owner key, holder's account) and waits in between.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from khutlisa import metal as mt  # noqa: E402

HOME = Path(os.environ.get("KHUTLISA_METAL_HOME") or mt.HOME)
CLI = [os.environ["KHUTLISA_METAL_CLI"]] if os.environ.get("KHUTLISA_METAL_CLI") else \
    [str(mt.LOCAL_CLI)] if mt.LOCAL_CLI.exists() else ["metal-agent"]
RPC_BARE = "https://rpc-testnet.metalntwx.com/v1"


def run(*args: str, rpc: str | None = None) -> tuple[int, str, str]:
    env = {**os.environ, "HOME": str(HOME / "home")}
    if rpc:
        env["METAL_RPC_URL"] = rpc
    done = subprocess.run([*CLI, *args], capture_output=True, text=True, env=env, timeout=300)
    return done.returncode, done.stdout, done.stderr


def say(text: str) -> None:
    print(mt.redact(text.rstrip()))


def private(path: Path) -> None:
    if path.exists():
        os.chmod(path, 0o600)


def address_of(key_file: Path) -> str:
    return json.loads(key_file.read_text())["address"]


def key(name: str, file: str = "key.json") -> str:
    folder = HOME / name
    folder.mkdir(parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    path = folder / file
    if not path.exists():
        code, out, err = run("key", "create", "--out", str(path))
        if code != 0:
            sys.exit(f"could not create the {name} key: {mt.redact(err)}")
    private(path)
    say(f"{name}: address {address_of(path)}")
    return address_of(path)


def fund(address: str, what: str) -> None:
    """Asks the faucet, waiting out its one-a-minute limit. An address that is already full is left alone."""
    for _ in range(6):
        code, out, err = run("fund", address, "--network", "testnet")
        if code == 0:
            say(f"{what}: " + " | ".join(out.strip().splitlines()))
            return
        wait = re.search(r"retry in (\d+) s", err)
        if "client_rate_limited" in err and wait:
            say(f"{what}: the faucet asks to wait {wait.group(1)} s")
            time.sleep(int(wait.group(1)) + 2)
            continue
        if "already" in (out + err):
            say(f"{what}: {(out + err).strip()}")
            return
        sys.exit(f"the faucet refused to fund {what}: {mt.redact(err or out)}")
    sys.exit(f"the faucet kept asking to wait; fund {address} from the console's Faucet page and run this again")


def main() -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    os.chmod(HOME, 0o700)
    (HOME / "home").mkdir(exist_ok=True)
    (HOME / "mandates").mkdir(exist_ok=True)
    os.umask(0o077)
    code, out, _ = run("--version")
    if code != 0:
        sys.exit("The Metal command line is not installed. Run `npm install` in tools/metal first.")
    say(f"metal-agent {out.strip()} (this code was run against {mt.CLI_VERSION})")

    agent = key("agent")
    settlement = key("settlement")

    rpc_file = HOME / "rpc_url"
    if not rpc_file.exists() or not rpc_file.read_text().strip():
        fund(agent, "agent")
        code, out, err = run("pay", RPC_BARE, "--network", "testnet", "--key", str(HOME / "agent" / "key.json"),
                             "--method", "POST", "--body", '{"jsonrpc":"2.0","id":1,"method":"eth_blockNumber","params":[]}')
        found = re.search(r"^header rpc-aas-endpoint: (\S+)$", out, re.M | re.I)
        if code != 0 or not found:
            sys.exit("could not buy an RPC endpoint: " + mt.redact(err or out)
                     + "\nIf a payment was signed, it may have settled: an address is handed one endpoint, so "
                       "running this again pays 1 *USDZ more and returns the same endpoint.")
        rpc_file.write_text(found.group(1))
        tx = re.search(r"^transaction (\S+)$", out, re.M)
        say(f"rpc endpoint: bought for 1 *USDZ, transaction {tx.group(1) if tx else 'unknown'}; URL stored in {rpc_file}")
    else:
        say(f"rpc endpoint: already stored in {rpc_file}")
    private(rpc_file)
    rpc = rpc_file.read_text().strip()

    holder = HOME / "holder"
    holder.mkdir(exist_ok=True)
    os.chmod(holder, 0o700)
    owner_key = holder / "owner-key.json"
    account = None
    for _ in range(4):
        code, out, err = run("account", "create", "--key" if owner_key.exists() else "--out", str(owner_key),
                             "--network", "testnet", rpc=rpc)
        fields = mt._fields(out)
        account = mt._first(fields, "account")
        if code == 0:
            say("holder: account " + str(account) + ", owner " + str(mt._first(fields, "owner"))
                + (", deployed in " + mt._first(fields, "transaction") if mt._first(fields, "transaction") else ""))
            break
        wait = re.search(r"retry in (\d+) s", err)
        if wait:
            say(f"holder: the faucet asks to wait {wait.group(1)} s")
            time.sleep(int(wait.group(1)) + 2)
            continue
        sys.exit("could not create the holder's account: " + mt.redact(err))
    else:
        sys.exit("the faucet kept asking to wait; run this again in a minute")
    for path in holder.iterdir():
        private(path)

    config = {"holder_account": account, "holder_owner": address_of(owner_key), "settlement": settlement,
              "agent": agent, "network": mt.NETWORK, "chain": mt.CHAIN}
    (HOME / "config.json").write_text(json.dumps(config, indent=2))
    private(HOME / "config.json")

    chain = mt.MetalCli(mt.MetalConfig.load())
    balance = chain.balance(account)
    if balance is None or float(balance) < 99:
        time.sleep(61)      # the faucet gives one grant a minute
        fund(account, "holder's account")
    say(f"holder's account holds {chain.balance(account)} *USDZ; agent holds {chain.balance(agent)} *USDZ")
    say(f"written {HOME / 'config.json'}: " + json.dumps(config))
    say("Explorer: " + mt.explorer_address(account))


if __name__ == "__main__":
    main()
