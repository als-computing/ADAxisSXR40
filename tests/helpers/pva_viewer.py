"""A stand-in for an image viewer: subscribe to an NTNDArray over pvAccess with the full
request, the way c2dataviewer / ImageJ do, and print one line per frame received.

    .venv/bin/python -m helpers.pva_viewer XV4040:Pva1:Image

Output, line-buffered:  ``frame <uniqueId> <bytes>``; ``connected`` / ``disconnected`` on
state changes. Needs p4p (pip install p4p). `pvmonitor` cannot play this role: a sub-field
request such as `field(uniqueId)` on the NDPluginPva record never sees an update (only the
full request does), and formatting 32 MiB frames as text makes it fall hopelessly behind.
"""
import os
import sys
import time


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    pv = argv[1]
    for k in ("EPICS_PVA_ADDR_LIST", "EPICS_PVA_AUTO_ADDR_LIST"):   # discovery is broadcast-only
        os.environ.pop(k, None)
    from p4p.client.thread import Context, Disconnected

    out = sys.stdout
    def cb(v):
        if isinstance(v, Disconnected):
            out.write("disconnected\n")
        elif isinstance(v, Exception):
            out.write(f"error {v}\n")
        else:
            raw = getattr(v, "raw", v)          # p4p unwraps NTNDArray into an ndarray subclass
            arr = raw["value"]
            out.write(f"frame {raw['uniqueId']} {getattr(arr, 'nbytes', 0)}\n")
        out.flush()

    ctx = Context("pva")
    sub = ctx.monitor(pv, cb, notify_disconnect=True)
    out.write("connected\n")
    out.flush()
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        sub.close()
        ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
