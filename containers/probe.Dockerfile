FROM registry.rossollc.com/hermes:latest
ENTRYPOINT []
CMD ["sh", "-c", "cat /etc/os-release; echo '---'; which hermes node npm qodercli 2>&1; echo '---'; hermes --version 2>&1 | head -5"]
