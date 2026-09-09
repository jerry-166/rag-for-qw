$token = (Invoke-RestMethod -Uri 'http://localhost:8003/api/auth/login' -Method Post -Body @{username='loadtester';password='Loadtest#123'}).access_token
$r = Invoke-WebRequest -Uri 'http://localhost:8003/api/knowledge_bases' -Headers @{Authorization="Bearer $token"} -UseBasicParsing
Write-Host $r.Content
