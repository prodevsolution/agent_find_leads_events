# install_ollama_windows.ps1 - Install Ollama and Phi-4 Mini on Windows

Write-Host "Checking if Ollama is installed..." -ForegroundColor Cyan

$ollamaPath = Get-Command ollama -ErrorAction SilentlyContinue

if ($null -eq $ollamaPath) {
    Write-Host "Ollama not found. Installing via direct download..." -ForegroundColor Yellow
    
    $url = "https://ollama.com/download/OllamaSetup.exe"
    $output = "$env:TEMP\OllamaSetup.exe"
    
    Invoke-WebRequest -Uri $url -OutFile $output
    Write-Host "Starting installer... Please follow the prompts." -ForegroundColor Green
    Start-Process -FilePath $output -Wait
} else {
    Write-Host "Ollama is already installed." -ForegroundColor Green
}

Write-Host "Pulling Phi-4 Mini model..." -ForegroundColor Cyan
ollama pull phi4-mini

Write-Host "Phi-4 Mini model is ready!" -ForegroundColor Green
