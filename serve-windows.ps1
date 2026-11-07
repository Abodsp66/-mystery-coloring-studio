# Local static HTTP server for Windows PowerShell 5.1; no Python/Node download.
$ErrorActionPreference = 'Stop'
$siteRoot = [System.IO.Path]::GetFullPath($PSScriptRoot)
$server = $null
foreach ($candidatePort in 8765..8785) {
    try {
        $connection = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $candidatePort)
        $connection.Start()
        $server = $connection
        $sitePort = $candidatePort
        break
    } catch { if ($connection) { $connection.Stop() } }
}
if (-not $server) { throw 'Cannot bind a localhost port (8765-8785).' }
$mimeTypes = @{
    '.html'='text/html; charset=utf-8'; '.mjs'='text/javascript; charset=utf-8'
    '.js'='text/javascript; charset=utf-8'; '.css'='text/css; charset=utf-8'
    '.json'='application/json'; '.svg'='image/svg+xml'; '.ttf'='font/ttf'
    '.png'='image/png'; '.jpg'='image/jpeg'; '.webp'='image/webp'; '.pdf'='application/pdf'
}
$address = "http://127.0.0.1:$sitePort/"
Write-Host "Flow Studio: $address"
Write-Host 'Keep this window open. Ctrl+C stops the local server. No network download is required.'
Start-Process $address
try {
    while ($true) {
        $client = $server.AcceptTcpClient()
        try {
            $client.ReceiveTimeout = 5000; $client.SendTimeout = 10000
            $stream = $client.GetStream()
            $reader = [System.IO.StreamReader]::new($stream, [System.Text.Encoding]::ASCII, $false, 8192, $true)
            $request = $reader.ReadLine()
            if ([string]::IsNullOrWhiteSpace($request)) { continue }
            for ($line = 0; $line -lt 80; $line++) { if ([string]::IsNullOrEmpty($reader.ReadLine())) { break } }
            $parts = $request.Split(' '); $statusCode = 200; $reason = 'OK'; $mime = 'text/plain'
            $body = [byte[]]@()
            if ($parts.Length -lt 2) { $statusCode = 400; $reason = 'Bad Request' }
            elseif ($parts[0] -notin @('GET','HEAD')) { $statusCode = 405; $reason = 'Method Not Allowed' }
            else {
                $urlPath = [System.Uri]::UnescapeDataString($parts[1].Split('?')[0])
                $relative = $urlPath.Replace('/', [System.IO.Path]::DirectorySeparatorChar).TrimStart([System.IO.Path]::DirectorySeparatorChar)
                if (-not $relative) { $relative = 'index.html' }
                $full = [System.IO.Path]::GetFullPath((Join-Path $siteRoot $relative))
                if (-not $full.StartsWith($siteRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
                    $statusCode = 403; $reason = 'Forbidden'
                } elseif (-not (Test-Path -LiteralPath $full -PathType Leaf)) { $statusCode = 404; $reason = 'Not Found' }
                else {
                    $extension = [System.IO.Path]::GetExtension($full).ToLowerInvariant()
                    if ($mimeTypes.ContainsKey($extension)) { $mime = $mimeTypes[$extension] }
                    else { $mime = 'application/octet-stream' }
                    $body = [System.IO.File]::ReadAllBytes($full)
                }
            }
            if ($statusCode -ne 200) { $body = [System.Text.Encoding]::UTF8.GetBytes("$statusCode $reason") }
            $header = "HTTP/1.1 $statusCode $reason`r`nContent-Type: $mime`r`nContent-Length: $($body.Length)`r`nCache-Control: no-store`r`nX-Content-Type-Options: nosniff`r`nConnection: close`r`n`r`n"
            $headBytes = [System.Text.Encoding]::ASCII.GetBytes($header)
            $stream.Write($headBytes,0,$headBytes.Length)
            if ($parts[0] -ne 'HEAD') { $stream.Write($body,0,$body.Length) }
        } catch { Write-Host $_.Exception.Message }
        finally { $client.Close() }
    }
} finally { $server.Stop() }
