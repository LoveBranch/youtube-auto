#!/usr/bin/env python3
"""Poll Stable Horde job and download result when done."""
import sys
import time
import json
import base64
import urllib.request
import urllib.error

def main():
    if len(sys.argv) < 3:
        print("Usage: poll_horde.py <job_id> <output_path>")
        sys.exit(1)

    job_id = sys.argv[1]
    output_path = sys.argv[2]

    check_url = f"https://stablehorde.net/api/v2/generate/check/{job_id}"
    status_url = f"https://stablehorde.net/api/v2/generate/status/{job_id}"

    print(f"Polling job: {job_id}")
    poll = 0
    while True:
        poll += 1
        try:
            with urllib.request.urlopen(check_url, timeout=30) as resp:
                data = json.loads(resp.read())
        except Exception as e:
            print(f"Poll {poll}: check error: {e}")
            time.sleep(15)
            continue

        done = data.get("done", False)
        faulted = data.get("faulted", False)
        queue = data.get("queue_position", "?")
        wait = data.get("wait_time", "?")
        print(f"Poll {poll}: done={done} faulted={faulted} queue={queue} wait={wait}s")

        if faulted:
            print("ERROR: Job faulted.")
            sys.exit(1)

        if done:
            print("Job done! Downloading result...")
            break

        time.sleep(15)

    # Fetch final status with image
    try:
        with urllib.request.urlopen(status_url, timeout=60) as resp:
            status = json.loads(resp.read())
    except Exception as e:
        print(f"Failed to fetch status: {e}")
        sys.exit(1)

    generations = status.get("generations", [])
    if not generations:
        print("No generations found in status response.")
        sys.exit(1)

    gen = generations[0]
    img_data = gen.get("img", "")

    if not img_data:
        print("No image data in response.")
        sys.exit(1)

    # img may be a URL or base64
    if img_data.startswith("http"):
        print(f"Downloading image from URL: {img_data}")
        try:
            with urllib.request.urlopen(img_data, timeout=60) as resp:
                image_bytes = resp.read()
        except Exception as e:
            print(f"Failed to download image: {e}")
            sys.exit(1)
    else:
        print("Decoding base64 image...")
        # Strip data URI prefix if present
        if "," in img_data:
            img_data = img_data.split(",", 1)[1]
        image_bytes = base64.b64decode(img_data)

    with open(output_path, "wb") as f:
        f.write(image_bytes)

    print(f"Saved thumbnail to: {output_path}")

if __name__ == "__main__":
    main()
