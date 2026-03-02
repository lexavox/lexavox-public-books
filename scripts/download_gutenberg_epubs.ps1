# download_gutenberg_epubs.ps1
# Run from lexavox-public-books repo root. Downloads EPUBs from Project Gutenberg into books/.
$ErrorActionPreference = "Continue"
$catalog = Get-Content -Raw "catalog.json" | ConvertFrom-Json
$baseUrl = "https://www.gutenberg.org/cache/epub"
foreach ($book in $catalog.books) {
  $id = $book.id -replace "pg", ""
  $url = "$baseUrl/$id/pg$id.epub"
  $path = "books/$($book.filename)"
  Write-Host "Downloading $($book.title)..."
  try {
    Invoke-WebRequest -Uri $url -OutFile $path -UseBasicParsing
    Start-Sleep -Seconds 2
  } catch {
    Write-Warning "Failed: $($book.filename) - $_"
  }
}
Write-Host "Done. Commit and push the books/ folder."
