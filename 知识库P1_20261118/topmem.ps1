Get-Process | Sort-Object WS -Descending |
  Select-Object -First 16 Name, Id, @{n='WS_MB';e={[int]($_.WS/1MB)}} |
  Format-Table -AutoSize