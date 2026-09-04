# FIM 간단 테스트 - 파일 10개 생성 -> 그 중 일부 수정 -> 그 중 일부 삭제
# 사용법: PowerShell -ExecutionPolicy Bypass -File fim_quick_test.ps1
#         (경로 바꾸고 싶으면: -Dir C:\다른경로)
param(
    [string]$Dir = "C:\fim_test"
)

if (-not (Test-Path $Dir)) {
    New-Item -ItemType Directory -Path $Dir -Force | Out-Null
}

Write-Host "== 대상 폴더: $Dir ==" -ForegroundColor Cyan

Write-Host "`n[1/3] 파일 10개 생성" -ForegroundColor Yellow
for ($i = 1; $i -le 10; $i++) {
    Set-Content -Path "$Dir\test_$i.txt" -Value "생성 시각: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    Write-Host "  생성: test_$i.txt"
}

Start-Sleep -Seconds 2

Write-Host "`n[2/3] 3개 수정 (test_1, test_2, test_3)" -ForegroundColor Yellow
foreach ($i in 1..3) {
    Add-Content -Path "$Dir\test_$i.txt" -Value "수정 시각: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    Write-Host "  수정: test_$i.txt"
}

Start-Sleep -Seconds 2

Write-Host "`n[3/3] 2개 삭제 (test_9, test_10)" -ForegroundColor Yellow
foreach ($i in 9..10) {
    Remove-Item -Path "$Dir\test_$i.txt" -Force
    Write-Host "  삭제: test_$i.txt"
}

Write-Host "`n완료. 남은 파일: $((Get-ChildItem $Dir -File).Count)개" -ForegroundColor Green
Write-Host "이제 '.\kavis-agent-windows.exe collect' 를 실행해서 FIM 탭에 반영되는지 확인하세요." -ForegroundColor Green
