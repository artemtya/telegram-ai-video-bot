# Скрипт для вызова SD API
import requests
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--input", required=True)
parser.add_argument("--output", required=True)
parser.add_argument("--style", required=True)
args = parser.parse_args()

response = requests.post(
    "http://localhost:7860/sdapi/v1/img2img",
    json={
        "init_images": [open(args.input, "rb").read()],
        "prompt": f"high quality, {args.style} style",
        "negative_prompt": "blurry, lowres, bad anatomy",
        "steps": 20,
        "denoising_strength": 0.7
    }
)
with open(args.output, "wb") as f:
    f.write(response.content)