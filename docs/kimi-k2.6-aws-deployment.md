# Deploy Kimi K2.6 for the Opinion Graph on AWS

This runbook deploys `moonshotai/Kimi-K2.6` behind an OpenAI-compatible endpoint
for the Agent Smith `opinion` graph. The graph expects the endpoint at
`OPINION_MODEL_BASE_URL` and uses thinking mode for both the worker and rubric
grader models.

Kimi K2.6 is a very large MoE model. Do not start with a small single-GPU
instance. Use `p5e.48xlarge` or `p5en.48xlarge` when available; use
`p5.48xlarge` only after capacity and context-length testing.

## 1. Choose Region and Capacity

1. Choose an AWS region with P5e or P5en capacity, usually `us-east-1`,
   `us-west-2`, or another region where your account already has GPU quota.
2. Request quota/capacity for `p5e.48xlarge` or `p5en.48xlarge`.
3. Confirm budget approval before launching. These instances are expensive and
   should be stopped or terminated immediately after testing.

## 2. Query the Latest Ubuntu 22.04 GPU DLAMI

```sh
export AWS_REGION=us-east-1
export SSM_PARAMETER=base-oss-nvidia-driver-gpu-ubuntu-22.04/latest/ami-id

aws ssm get-parameter --region "$AWS_REGION" \
  --name /aws/service/deeplearning/ami/x86_64/$SSM_PARAMETER \
  --query "Parameter.Value" \
  --output text
```

Use the returned AMI ID when launching the EC2 instance.

## 3. Launch the Instance

Launch one of these instance types:

- Preferred: `p5en.48xlarge`
- Preferred: `p5e.48xlarge`
- Fallback: `p5.48xlarge`

Security group requirements:

- Allow SSH (`22`) only from the operator's current IP.
- Do not expose `30000` to the public internet.
- If another service needs to reach the model inside a VPC, allow `30000` only
  from that private security group or subnet.

Storage:

- Start with at least 2 TiB of gp3 EBS if you do not plan to rely only on the
  instance NVMe cache.
- Keep Hugging Face cache data on fast local storage where possible.

## 4. Verify GPU and Docker

SSH to the host:

```sh
ssh ubuntu@<ec2-host>
```

Verify the GPUs:

```sh
nvidia-smi
```

Verify Docker can see the GPUs:

```sh
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

If either command fails, stop here and fix the AMI, driver, or Docker runtime
configuration before downloading model weights.

## 5. Start SGLang

Authenticate Hugging Face:

```sh
export HF_TOKEN=<token>
```

Start the OpenAI-compatible SGLang server:

```sh
docker run --gpus all --shm-size 32g --ipc=host \
  -p 30000:30000 \
  -v ~/.cache/huggingface:/root/.cache/huggingface \
  -e HF_TOKEN="$HF_TOKEN" \
  lmsysorg/sglang:latest \
  python3 -m sglang.launch_server \
    --model-path moonshotai/Kimi-K2.6 \
    --host 0.0.0.0 \
    --port 30000 \
    --tp-size 8
```

Keep this shell open for first-run logs. The initial weight download and model
startup can take a long time.

## 6. Verify Inference on the Instance

From the EC2 host:

```sh
curl http://localhost:30000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"moonshotai/Kimi-K2.6","messages":[{"role":"user","content":"Which is bigger, 9.11 or 9.9? Think carefully."}],"temperature":1.0,"top_p":0.95,"max_tokens":512,"extra_body":{"chat_template_kwargs":{"thinking":true}}}'
```

Expected result: HTTP 200 with a chat completion that reasons correctly that
`9.9` is larger than `9.11`.

If SGLang rejects the nested `extra_body` shape for direct curl requests, retry
with `chat_template_kwargs` as a top-level request field. Keep Agent Smith's
LangChain config unchanged; LangChain passes provider-specific parameters
through `extra_body`.

## 7. Tunnel the Endpoint to Local Agent Smith

From the local machine running Agent Smith:

```sh
ssh -N -L 30000:localhost:30000 ubuntu@<ec2-host>
```

Leave the tunnel open while testing the graph.

## 8. Configure Agent Smith

Set these values in `.env.development` or the active environment file:

```sh
OPINION_MODEL=moonshotai/Kimi-K2.6
OPINION_MODEL_BASE_URL=http://localhost:30000/v1
OPINION_MODEL_API_KEY=local-kimi
OPINION_RULE_AGENT=codex
OPINION_RULE_INCLUDE=DRY,Easier To Change,Design by Contract,No Broken Windows,Tracer Bullets
OPINION_RUBRIC_MAX_ITERATIONS=3
```

The API key can be any non-empty value unless the SGLang server is placed behind
an authentication proxy.

## 9. Run an End-to-End Smoke Test

From the Agent Smith repo:

```sh
.venv/bin/python -c 'import asyncio; from services.graphs.runtime import dispatch; print(asyncio.run(dispatch("opinion", {"proposal": "Add a new service for X."})))'
```

Expected result: a candid engineering opinion that covers strengths, biggest
risk, simplifications, assumptions, and applies the configured pragmatic rules.

## 10. Cleanup

When testing is complete:

1. Stop the SGLang container with `Ctrl-C` or `docker stop <container-id>`.
2. Stop or terminate the EC2 instance.
3. Delete unused EBS volumes if the instance was terminated but storage remains.
4. Delete model caches only if you do not plan to restart the endpoint soon.
5. Remove any temporary public security group ingress rules.

Never leave a P5-class instance running unattended.
