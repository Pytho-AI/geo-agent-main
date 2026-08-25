"""TCP forwarder: 172.17.0.1:9222 -> 127.0.0.1:9222.

Chromium binds --remote-debugging-port to 127.0.0.1 only (the
--remote-debugging-address flag is ignored in headless mode on some
versions). This forwarder exposes that loopback-bound CDP to the
docker bridge so docker-api containers can reach it.

Required because:
  - Host Chromium = needed for GB10 GPU acceleration
  - 127.0.0.1 = NOT reachable from inside docker (the bridge sees
    its own gateway IP, not host loopback)
  - So forward at the TCP layer

Started by the USER-scope unit ~/.config/systemd/user/cdp-forward.service
(installed by scripts/install_geoagent.sh --host-render), after
chromium-cdp.service is healthy.
"""
import asyncio


async def handle(reader, writer):
    try:
        up_r, up_w = await asyncio.open_connection("127.0.0.1", 9222)
    except Exception:
        writer.close()
        return

    async def pump(r, w):
        try:
            while True:
                d = await r.read(65536)
                if not d:
                    break
                w.write(d)
                await w.drain()
        except Exception:
            pass
        try:
            w.close()
        except Exception:
            pass

    await asyncio.gather(pump(reader, up_w), pump(up_r, writer))


async def main():
    s = await asyncio.start_server(handle, "172.17.0.1", 9222)
    async with s:
        await s.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
