"""Payment verification.

- UPI aur Binance ID: manual (user reference bhejta hai, admin approve karta hai).
- USDT BEP20: blockchain se automatic verify (BSC JSON-RPC, Transfer event ka amount).
"""
import json
import re
import urllib.request
from decimal import Decimal

from db import ApiError

TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
UTR_RE = re.compile(r"^\d{12}$")
TX_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")
BINANCE_REF_RE = re.compile(r"^[A-Za-z0-9_\-]{6,64}$")
ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


def rpc_call(url, method, params):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=12) as r:
        out = json.loads(r.read().decode())
    if "error" in out:
        raise RuntimeError(str(out["error"]))
    return out.get("result")


def validate_reference(method, ref):
    ref = (ref or "").strip()
    if method == "upi":
        if not UTR_RE.match(ref):
            raise ApiError(400, "UTR must be exactly 12 digits")
    elif method == "binance_id":
        if not BINANCE_REF_RE.match(ref):
            raise ApiError(400, "Invalid Binance transaction/order ID")
    elif method == "usdt_bep20":
        if not TX_RE.match(ref):
            raise ApiError(400, "Invalid transaction hash (0x followed by 64 hex characters)")
        ref = ref.lower()
    else:
        raise ApiError(400, "Invalid payment method")
    return ref


def verify_usdt_bep20(tx_hash, settings, call=rpc_call):
    """Return amount (Decimal, USDT) jo hamare address par aaya. Error par ApiError.

    Sirf confirmed, successful tx maanta hai aur sirf USDT contract ke Transfer events
    jinka 'to' hamara address ho. User ka bataya hua amount kabhi use nahi hota.
    """
    to_addr = settings.get("usdt_address", "").strip().lower()
    contract = settings.get("usdt_contract", "").strip().lower()
    rpc = settings.get("bsc_rpc", "").strip()
    need = int(settings.get("confirmations", "10") or 10)
    if not (ADDR_RE.match(to_addr) and ADDR_RE.match(contract) and rpc):
        raise ApiError(503, "USDT payments are not set up yet")
    try:
        receipt = call(rpc, "eth_getTransactionReceipt", [tx_hash])
        head = int(call(rpc, "eth_blockNumber", []), 16)
    except Exception:
        raise ApiError(502, "The blockchain did not respond. Please try again shortly")
    if not receipt:
        raise ApiError(409, "Transaction not found yet. Please try again after it is confirmed")
    if receipt.get("status") != "0x1":
        raise ApiError(400, "This transaction failed on the blockchain")
    conf = head - int(receipt["blockNumber"], 16) + 1
    if conf < need:
        raise ApiError(409, "Confirmations %d/%d. Please try again shortly" % (max(conf, 0), need))
    total = Decimal(0)
    for lg in receipt.get("logs", []):
        topics = lg.get("topics", [])
        if (lg.get("address", "").lower() == contract and len(topics) == 3
                and topics[0].lower() == TRANSFER_TOPIC
                and "0x" + topics[2][-40:].lower() == to_addr):
            total += Decimal(int(lg["data"], 16)) / Decimal(10 ** 18)
    if total <= 0:
        raise ApiError(400, "This transaction did not send USDT to our address")
    return total
