FROM nousresearch/hermes-agent:latest

USER root

# Install lark-cli
RUN npm install -g @larksuite/cli@latest

USER node
