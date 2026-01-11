import asyncio
import websockets

async def test_ws():
    uri = "ws://127.0.0.1:8000/ws"
    try:
        async with websockets.connect(uri) as ws:
            print("connected")
            # print a few messages
            for _ in range(3):
                msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                print("recv:", msg)
            # keep open for a couple more seconds
            await asyncio.sleep(2)
    except Exception as e:
        print('ws error', e)

if __name__ == '__main__':
    asyncio.run(test_ws())