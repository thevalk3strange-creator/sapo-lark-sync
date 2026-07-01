FROM nousresearch/hermes-agent:latest

USER root

# Install lark-cli globally
RUN npm install -g @larksuite/cli@latest

# Copy lark-base skill into Hermes skills directory
COPY skills/lark-base/SKILL.md /opt/hermes/skills/lark-base/SKILL.md

USER node
