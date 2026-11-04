# Localhost-only web server. No Python / Node.js required on Windows.
# Windows PowerShell 5.1 compatible. No external commands or installs.
$ErrorActionPreference = 'Stop'
$root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'dist'))
if (-not (Test-Path (Join-Path $root 'index.html'))) {
  Write-Host 'dist/index.html not found. Extract all ZIP contents.' -ForegroundColor Red
  exit 1
}
$listener = $null
$port = $null
foreach ($candidate in 8765..8785) {
  try {
    $l = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, [int]$candidate)
    $l.Start()
    $listener = $l
    $port = $candidate
    break
  } catch {
    if ($l -ne $null) { try { $l.Stop() } catch {} }
    $l = $null
  }
}
if ($null -eq $listener) {
  Write-Host 'Could not bind to localhost ports 8765-8785.' -ForegroundColor Red
  exit 1
}
$site = "http://127.0.0.1:$port/"
Write-Host "Local server running: $site" -ForegroundColor Green
Write-Host 'Keep this window open while using the studio. Press Ctrl+C to stop.'
Write-Host 'Internet is required at first to load Pyodide, NumPy, SciPy and Shapely from jsDelivr.'
Start-Process $site
$mimes = @{
  '.html'='text/html; charset=utf-8'
  '.js'='application/javascript; charset=utf-8'
  '.css'='text/css; charset=utf-8'
  '.json'='application/json; charset=utf-8'
  '.py'='text/plain; charset=utf-8'
  '.svg'='image/svg+xml'
  '.png'='image/png'
  '.jpg'='image/jpeg'
  '.jpeg'='image/jpeg'
  '.ico'='image/x-icon'
}
try {
  while ($true) {
    $client = $listener.AcceptTcpClient()
    try {
      $client.ReceiveTimeout = 5000
      $client.SendTimeout = 10000
      $stream = $client.GetStream()
      $stream.ReadTimeout = 5000
      $reader = New-Object System.IO.StreamReader($stream, [System.Text.Encoding]::ASCII, $false, 8192, $true)
      $requestLine = $reader.ReadLine()
      if ([string]::IsNullOrWhiteSpace($requestLine)) { continue }
      # Discard request headers (the server only accepts static GET/HEAD requests).
      for ($i = 0; $i -lt 80; $i++) {
        $headerLine = $reader.ReadLine()
        if ([string]::IsNullOrEmpty($headerLine)) { break }
      }
      $parts = $requestLine.Split(' ')
      $method = $parts[0]
      $code = 200
      $phrase = 'OK'
      $mime = 'text/plain; charset=utf-8'
      $body = [byte[]]@()
      if ($method -ne 'GET' -and $method -ne 'HEAD') {
        $code = 405; $phrase = 'Method Not Allowed'
      } elseif ($parts.Length -lt 2) {
        $code = 400; $phrase = 'Bad Request'
      } else {
        $urlPart = $parts[1].Split('?')[0]
        $path = [System.Uri]::UnescapeDataString($urlPart).Replace('/', [System.IO.Path]::DirectorySeparatorChar)
        $relative = $path.TrimStart([System.IO.Path]::DirectorySeparatorChar)
        if ([string]::IsNullOrWhiteSpace($relative)) { $relative = 'index.html' }
        $full = [System.IO.Path]::GetFullPath((Join-Path $root $relative))
        if (-not $full.StartsWith($root + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
          $code = 403; $phrase = 'Forbidden'
        } elseif (-not (Test-Path -LiteralPath $full -PathType Leaf)) {
          $code = 404; $phrase = 'Not Found'
        } else {
          $ext = [System.IO.Path]::GetExtension($full).ToLowerInvariant()
          if ($mimes.ContainsKey($ext)) { $mime = $mimes[$ext] }
          else { $mime = 'application/octet-stream' }
          $body = [System.IO.File]::ReadAllBytes($full)
        }
      }
      if ($code -ne 200) { $body = [System.Text.Encoding]::UTF8.GetBytes("$code $phrase") }
      $headers = "HTTP/1.1 $code $phrase`r`nContent-Type: $mime`r`nContent-Length: $($body.Length)`r`nConnection: close`r`nCache-Control: no-store`r`nX-Content-Type-Options: nosniff`r`n`r`n"
      $headBytes = [System.Text.Encoding]::ASCII.GetBytes($headers)
      $stream.Write($headBytes, 0, $headBytes.Length)
      if ($method -ne 'HEAD' -and $body.Length -gt 0) { $stream.Write($body, 0, $body.Length) }
    } catch {
      Write-Host "Request error: $($_.Exception.Message)" -ForegroundColor Yellow
    } finally {
      $client.Close()
    }
  }
} finally {
  $listener.Stop()
}
