#!/bin/bash

# install_ollama_linux.sh - Install Ollama and Phi-4 Mini on Linux

# Check if Ollama is already installed
if ! command -v ollama &> /dev/null
then
    echo "Ollama could not be found. Installing..."
    curl -fsSL https://ollama.com/install.sh | sh
else
    echo "Ollama is already installed."
fi

# Start Ollama service if not running (depends on systemd typically after installation)
# This script assumes the installation handles the service setup.

echo "Pulling Phi-4 Mini model..."
ollama pull phi4-mini

echo "Phi-4 Mini model is ready!"
