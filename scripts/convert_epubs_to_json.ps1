# convert_epubs_to_json.ps1
# Converts every EPUB in books/ to canonical JSON in json/
# and emits json/manifest.json with integrity metadata.

param(
  [string]$RepoRoot = "."
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Get-EntryText {
  param(
    [System.IO.Compression.ZipArchive]$Archive,
    [string]$EntryPath
  )
  $entry = $Archive.GetEntry($EntryPath)
  if (-not $entry) { return $null }
  $stream = $entry.Open()
  try {
    $reader = New-Object System.IO.StreamReader($stream, [System.Text.Encoding]::UTF8, $true)
    try { return $reader.ReadToEnd() } finally { $reader.Dispose() }
  } finally {
    $stream.Dispose()
  }
}

function Normalize-PathInZip {
  param(
    [string]$BaseDir,
    [string]$Href
  )
  $raw = if ([string]::IsNullOrWhiteSpace($BaseDir)) { $Href } else { "$BaseDir/$Href" }
  $raw = $raw.Replace("\", "/")
  $segments = $raw.Split("/")
  $normalized = New-Object System.Collections.Generic.List[string]
  foreach ($segment in $segments) {
    if ([string]::IsNullOrWhiteSpace($segment) -or $segment -eq ".") { continue }
    if ($segment -eq "..") {
      if ($normalized.Count -gt 0) { $normalized.RemoveAt($normalized.Count - 1) }
      continue
    }
    $normalized.Add($segment)
  }
  return ($normalized -join "/")
}

function Get-DirectoryPath {
  param([string]$PathValue)
  $index = $PathValue.LastIndexOf("/")
  if ($index -lt 0) { return "" }
  return $PathValue.Substring(0, $index)
}

function Strip-HtmlToParagraphs {
  param([string]$Html)
  if ([string]::IsNullOrWhiteSpace($Html)) { return @() }

  $text = $Html
  $text = [System.Text.RegularExpressions.Regex]::Replace($text, "(?is)<script[\s\S]*?</script>", " ")
  $text = [System.Text.RegularExpressions.Regex]::Replace($text, "(?is)<style[\s\S]*?</style>", " ")
  $text = [System.Text.RegularExpressions.Regex]::Replace($text, "(?i)<br\s*/?>", "`n")
  $text = [System.Text.RegularExpressions.Regex]::Replace($text, "(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|tr|section|article|blockquote)>", "`n")
  $text = [System.Text.RegularExpressions.Regex]::Replace($text, "<[^>]+>", " ")
  $text = [System.Net.WebUtility]::HtmlDecode($text)
  $text = $text.Replace("`r", "")
  $text = [System.Text.RegularExpressions.Regex]::Replace($text, "[\t ]+", " ")
  $text = [System.Text.RegularExpressions.Regex]::Replace($text, " *`n *", "`n")
  $text = [System.Text.RegularExpressions.Regex]::Replace($text, "`n{3,}", "`n`n")
  $text = $text.Trim()
  if ([string]::IsNullOrWhiteSpace($text)) { return @() }

  $parts = $text -split "`n{2,}"
  $paragraphs = @()
  foreach ($part in $parts) {
    $clean = ($part -replace "\s+", " ").Trim()
    if (-not [string]::IsNullOrWhiteSpace($clean)) {
      $paragraphs += $clean
    }
  }
  return $paragraphs
}

function Compute-Sha256Hex {
  param([string]$TextValue)
  $bytes = [System.Text.Encoding]::UTF8.GetBytes($TextValue)
  $sha = [System.Security.Cryptography.SHA256]::Create()
  try {
    $hash = $sha.ComputeHash($bytes)
    return (-join ($hash | ForEach-Object { $_.ToString("x2") }))
  } finally {
    $sha.Dispose()
  }
}

$repo = Resolve-Path $RepoRoot
$booksRoot = Join-Path $repo "books"
$jsonRoot = Join-Path $repo "json"
$catalogPath = Join-Path $repo "catalog.json"

if (-not (Test-Path $booksRoot)) {
  throw "books/ directory not found at $booksRoot"
}
if (-not (Test-Path $catalogPath)) {
  throw "catalog.json not found at $catalogPath"
}

$catalog = Get-Content -Raw $catalogPath | ConvertFrom-Json
$catalogLookup = @{}
foreach ($book in $catalog.books) {
  $catalogLookup[$book.filename] = $book
}

if (Test-Path $jsonRoot) {
  Remove-Item $jsonRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $jsonRoot | Out-Null

$epubFiles = Get-ChildItem -Path $booksRoot -Recurse -File -Filter *.epub
$manifestBooks = @()

foreach ($epub in $epubFiles) {
  $relativeBookPath = $epub.FullName.Substring($booksRoot.Length).TrimStart("\", "/")
  $relativeBookPath = $relativeBookPath.Replace("\", "/")
  $bookFilename = $epub.Name
  $bookMeta = $catalogLookup[$bookFilename]

  Write-Host "Converting $relativeBookPath"

  $zip = [System.IO.Compression.ZipFile]::OpenRead($epub.FullName)
  try {
    $containerXml = Get-EntryText -Archive $zip -EntryPath "META-INF/container.xml"
    $rootFilePath = $null
    if (-not [string]::IsNullOrWhiteSpace($containerXml)) {
      $match = [System.Text.RegularExpressions.Regex]::Match(
        $containerXml,
        "(?i)<rootfile[^>]*full-path=['""]([^'""]+)['""]"
      )
      if ($match.Success) {
        $rootFilePath = $match.Groups[1].Value.Trim()
      }
    }

    $chapterPaths = @()
    if (-not [string]::IsNullOrWhiteSpace($rootFilePath)) {
      $opfXml = Get-EntryText -Archive $zip -EntryPath $rootFilePath
      if (-not [string]::IsNullOrWhiteSpace($opfXml)) {
        $baseDir = Get-DirectoryPath -PathValue $rootFilePath
        $manifest = @{}
        $manifestMatches = [System.Text.RegularExpressions.Regex]::Matches(
          $opfXml,
          "(?i)<item[^>]*id=['""]([^'""]+)['""][^>]*href=['""]([^'""]+)['""][^>]*>"
        )
        foreach ($m in $manifestMatches) {
          $id = $m.Groups[1].Value.Trim()
          $href = $m.Groups[2].Value.Trim()
          if (-not [string]::IsNullOrWhiteSpace($id) -and -not [string]::IsNullOrWhiteSpace($href)) {
            $manifest[$id] = $href
          }
        }

        $spineMatches = [System.Text.RegularExpressions.Regex]::Matches(
          $opfXml,
          "(?i)<itemref[^>]*idref=['""]([^'""]+)['""][^>]*>"
        )
        foreach ($m in $spineMatches) {
          $idref = $m.Groups[1].Value.Trim()
          if ($manifest.ContainsKey($idref)) {
            $chapterPaths += (Normalize-PathInZip -BaseDir $baseDir -Href $manifest[$idref])
          }
        }
      }
    }

    if ($chapterPaths.Count -eq 0) {
      $chapterPaths = @(
        $zip.Entries |
          Where-Object {
            -not [string]::IsNullOrWhiteSpace($_.Name) -and
            ($_.FullName.ToLower().EndsWith(".xhtml") -or
             $_.FullName.ToLower().EndsWith(".html") -or
             $_.FullName.ToLower().EndsWith(".htm"))
          } |
          Sort-Object FullName |
          ForEach-Object { $_.FullName }
      )
    }

    $paragraphs = New-Object System.Collections.Generic.List[object]
    $chapterSummaries = New-Object System.Collections.Generic.List[object]
    $order = 0
    $chapterIndex = 0

    foreach ($chapterPath in $chapterPaths) {
      $chapterText = Get-EntryText -Archive $zip -EntryPath $chapterPath
      $chapterParagraphs = Strip-HtmlToParagraphs -Html $chapterText
      if ($chapterParagraphs.Count -eq 0) {
        $chapterIndex += 1
        continue
      }

      foreach ($p in $chapterParagraphs) {
        $paragraphs.Add([pscustomobject]@{
          order = $order
          chapterIndex = $chapterIndex
          text = $p
        })
        $order += 1
      }

      $chapterSummaries.Add([pscustomobject]@{
        chapterIndex = $chapterIndex
        sourcePath = $chapterPath
        paragraphCount = $chapterParagraphs.Count
      })
      $chapterIndex += 1
    }

    $orderedText = ($paragraphs | ForEach-Object { $_.text }) -join "`n`n"
    $charCount = $orderedText.Length
    $wordCount = if ([string]::IsNullOrWhiteSpace($orderedText)) { 0 } else { (($orderedText -split "\s+") | Where-Object { $_.Trim().Length -gt 0 }).Count }
    $sha256 = Compute-Sha256Hex -TextValue $orderedText

    $jsonRelativePath = [System.IO.Path]::ChangeExtension($relativeBookPath, ".json").Replace("\", "/")
    $jsonOutputPath = Join-Path $jsonRoot $jsonRelativePath
    $jsonOutputDir = Split-Path -Parent $jsonOutputPath
    if (-not (Test-Path $jsonOutputDir)) {
      New-Item -ItemType Directory -Path $jsonOutputDir -Force | Out-Null
    }

    $payload = [ordered]@{
      schemaVersion = 1
      generatedAt = [DateTime]::UtcNow.ToString("o")
      source = [ordered]@{
        id = if ($bookMeta) { $bookMeta.id } else { $bookFilename }
        title = if ($bookMeta) { $bookMeta.title } else { [System.IO.Path]::GetFileNameWithoutExtension($bookFilename) }
        author = if ($bookMeta) { $bookMeta.author } else { "Unknown" }
        language = if ($bookMeta) { $bookMeta.language } else { "en" }
        category = if ($bookMeta) { $bookMeta.category } else { "unknown" }
        filename = $bookFilename
        relativePath = $relativeBookPath
      }
      extraction = [ordered]@{
        strategy = "epub-spine-order"
        chapterCount = $chapterSummaries.Count
        paragraphCount = $paragraphs.Count
      }
      integrity = [ordered]@{
        sha256 = $sha256
        characterCount = $charCount
        wordCount = $wordCount
      }
      chapters = $chapterSummaries
      paragraphs = $paragraphs
    }

    $jsonText = ($payload | ConvertTo-Json -Depth 12)
    Set-Content -Path $jsonOutputPath -Value $jsonText -Encoding UTF8

    $manifestBooks += [pscustomobject]@{
      id = $payload.source.id
      title = $payload.source.title
      category = $payload.source.category
      epubPath = $relativeBookPath
      jsonPath = ("json/" + $jsonRelativePath)
      sha256 = $sha256
      chapterCount = $chapterSummaries.Count
      paragraphCount = $paragraphs.Count
      characterCount = $charCount
      wordCount = $wordCount
    }
  } finally {
    $zip.Dispose()
  }
}

$manifest = [ordered]@{
  schemaVersion = 1
  generatedAt = [DateTime]::UtcNow.ToString("o")
  sourceCatalogVersion = $catalog.version
  bookCount = $manifestBooks.Count
  books = $manifestBooks | Sort-Object title
}

$manifestPath = Join-Path $jsonRoot "manifest.json"
Set-Content -Path $manifestPath -Value ($manifest | ConvertTo-Json -Depth 6) -Encoding UTF8

Write-Host "Converted $($manifest.bookCount) EPUB files to JSON."
Write-Host "Manifest: $manifestPath"
