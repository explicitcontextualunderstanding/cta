FROM registry.rossollc.com/hermes:latest
ENTRYPOINT []
CMD ["sh", "-c", "node --version; npm --version; npm root -g; ls /opt/hermes 2>&1 | head; echo '---HOME---'; echo $HOME; ls -la $HOME 2>&1 | head -20"]
