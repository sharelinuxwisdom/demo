import asyncio
import time
import aiohttp
import argparse
import sys

# ---------- DEFAULT CONFIG ----------
DEFAULT_QUERY = "hello-world"
DEFAULT_TOTAL_REQUESTS = 500
DEFAULT_CONCURRENCY = 50
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = "8000"


def parse_args():
    parser = argparse.ArgumentParser(description="Async Load Testing Client")

    parser.add_argument("--default-test", action="store_true",
                        help="Run with predefined default values")

    parser.add_argument("--query", type=str, help="Query parameter value")
    parser.add_argument("--requests", type=int, help="Total number of requests")
    parser.add_argument("--concurrency", type=int, help="Concurrency level")
    parser.add_argument("--host", type=str, default=DEFAULT_HOST,
                        help=f"Target host (default: {DEFAULT_HOST})")
    parser.add_argument("--port", type=str, default=DEFAULT_PORT,
                        help=f"Target port (default: {DEFAULT_PORT})")

    args = parser.parse_args()

    if args.default_test:
        return {
            "query": DEFAULT_QUERY,
            "total_requests": DEFAULT_TOTAL_REQUESTS,
            "concurrency": DEFAULT_CONCURRENCY,
            "host": DEFAULT_HOST,
            "port": DEFAULT_PORT
        }

    # If not default test, require mandatory parameters
    if not (args.query and args.requests and args.concurrency):
        print("\nError: You must either use --default-test OR provide "
              "--query --requests --concurrency\n")
        parser.print_help()
        sys.exit(1)

    return {
        "query": args.query,
        "total_requests": args.requests,
        "concurrency": args.concurrency,
        "host": args.host,
        "port": args.port
    }


async def worker(session, sem, url):
    async with sem:
        start = time.perf_counter()
        try:
            async with session.get(url, timeout=10) as resp:
                await resp.text()
                latency_ms = (time.perf_counter() - start) * 1000
                return resp.status, latency_ms
        except Exception:
            latency_ms = (time.perf_counter() - start) * 1000
            return "ERR", latency_ms


async def run_test(config):
    url = f"http://{config['host']}:{config['port']}/chat/?query={config['query']}"
    sem = asyncio.Semaphore(config["concurrency"])

    print("\n===== TEST CONFIG =====")
    print(f"URL: {url}")
    print(f"Total Requests: {config['total_requests']}")
    print(f"Concurrency: {config['concurrency']}")
    print("========================\n")

    t0 = time.perf_counter()

    async with aiohttp.ClientSession() as session:
        tasks = [
            worker(session, sem, url)
            for _ in range(config["total_requests"])
        ]
        results = await asyncio.gather(*tasks)

    total_time = time.perf_counter() - t0

    ok = [r for r in results if r[0] == 200]
    err = [r for r in results if r[0] != 200]

    latencies = sorted([r[1] for r in ok])

    def percentile(p):
        if not latencies:
            return 0
        k = int((p / 100) * (len(latencies) - 1))
        return latencies[k]

    print("===== RESULTS =====")
    print(f"Completed in: {total_time:.2f} sec")
    print(f"Throughput: {config['total_requests'] / total_time:.2f} req/sec")
    print(f"Success: {len(ok)}")
    print(f"Errors: {len(err)}")

    if latencies:
        print(f"Latency ms -> "
              f"p50: {percentile(50):.2f}, "
              f"p90: {percentile(90):.2f}, "
              f"p99: {percentile(99):.2f}, "
              f"max: {latencies[-1]:.2f}")


if __name__ == "__main__":
    config = parse_args()
    asyncio.run(run_test(config))

'''
python client.py --query hello123 --requests 1000 --concurrency 100 --host 127.0.0.1 --port 8000

'''

