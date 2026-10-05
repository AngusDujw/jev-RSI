"""Expose an existing loopback TCP service through additional loopback ports.

Byte-transparent forwarding supports HTTP CONNECT and SOCKS without handling
credentials or changing the upstream proxy configuration. Run in foreground.
"""
import argparse
import asyncio
import datetime as dt
import json
import os
from pathlib import Path
import signal


async def serve(args):
    host = '127.0.0.1'
    servers, tasks = [], set()
    stop = asyncio.Event()
    stats = dict(accepted_connections=0, connection_errors=0)
    state = dict(pid=os.getpid(), listen_host=host, listen_ports=args.ports,
        target_host=host, target_port=args.target_port,
        started_at=dt.datetime.now(dt.timezone.utc).isoformat(), status='starting')

    def save(status):
        state.update(status=status, **stats)
        args.state_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.state_file.with_suffix('.new')
        temporary.write_text(json.dumps(state, indent=2)+'\n')
        temporary.replace(args.state_file)

    async def pipe(reader, writer):
        try:
            while True:
                data = await asyncio.wait_for(reader.read(65536), args.idle_seconds)
                if not data:
                    break
                writer.write(data)
                await writer.drain()
        except (ConnectionError, asyncio.TimeoutError):
            pass
        finally:
            if writer.can_write_eof() and not writer.is_closing():
                try:
                    writer.write_eof()
                    await writer.drain()
                except ConnectionError:
                    pass

    async def forward(reader, writer):
        task = asyncio.current_task(); tasks.add(task)
        upstream = None
        stats['accepted_connections'] += 1
        try:
            other_reader, upstream = await asyncio.wait_for(
                asyncio.open_connection(host, args.target_port), timeout=5)
            await asyncio.gather(pipe(reader, upstream), pipe(other_reader, writer))
        except (OSError, asyncio.TimeoutError):
            stats['connection_errors'] += 1
        finally:
            for stream in [writer, upstream]:
                if stream is not None:
                    stream.close()
                    try:
                        await stream.wait_closed()
                    except (ConnectionError, asyncio.CancelledError):
                        pass
            tasks.discard(task)

    if args.state_file.exists():
        raise RuntimeError('State file already exists; choose a new owned state path')
    loop = asyncio.get_running_loop()
    for sig in [signal.SIGINT, signal.SIGTERM]:
        loop.add_signal_handler(sig, stop.set)
    try:
        # Check the target before listening; no protocol request or model call.
        _, target = await asyncio.wait_for(asyncio.open_connection(host, args.target_port), 5)
        target.close(); await target.wait_closed()
        for port in args.ports:
            servers.append(await asyncio.start_server(forward, host, port,
                reuse_address=False, reuse_port=False))
        save('ready')
        print(json.dumps(state), flush=True)
        await stop.wait()
    except Exception as error:
        state['error'] = str(error)
        save('failed')
        raise
    finally:
        for server in servers:
            server.close()
        await asyncio.gather(*(server.wait_closed() for server in servers))
        for task in list(tasks):
            task.cancel()
        await asyncio.gather(*list(tasks), return_exceptions=True)
        if state['status'] != 'failed':
            save('stopped')
        print(json.dumps(state), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ports', type=int, nargs='+', required=True)
    parser.add_argument('--target-port', type=int, default=7897)
    parser.add_argument('--idle-seconds', type=int, default=300)
    parser.add_argument('--state-file', type=Path, required=True)
    args = parser.parse_args()
    if (len(set(args.ports)) != len(args.ports) or
        not all(1024 <= port <= 65535 for port in [*args.ports, args.target_port]) or
        args.target_port in args.ports or args.idle_seconds <= 0):
        parser.error('Unique unprivileged ports, no target loop, positive idle timeout required')
    asyncio.run(serve(args))


if __name__ == '__main__':
    main()
