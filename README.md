# Voca

Renames TV episode files using the [TVmaze API](https://www.tvmaze.com/api).

Given a directory of video files, Voca fetches episode titles for the correct show and season, then renames files to the format `NN Title.ext`.

## Requirements

Python 3, `requests` (`pip3 install requests`)

## Usage

```
voca.py [options] [dir]
```

`dir` defaults to the current directory. Voca detects whether it contains a single season, season subfolders, or a multi-show library, and processes accordingly.

### Options

| Flag | Description |
|------|-------------|
| `-i ID` | TVmaze show ID |
| `-l URL` | Link to show on tvmaze.com or api.tvmaze.com |
| `-n NAME` | Exact show name to search (e.g. `"The Office"`) |
| `-s N` | Season number |
| `-f EXT` | Only process files with this extension |
| `-Q [TERM]` | Query TVmaze: show info if given an ID, search results if given a name |
| `-m` | Manually select from top 3 search results |
| `-S` | Assume season folders are in series order without prompting |
| `-x FOLDER` | Ignore a folder by name (repeatable) |
| `-j` | Sort files numerically instead of alphabetically |
| `-g` | Gentle mode: don't rename any folders |
| `-p` | Preview renames without executing |
| `-e EPISODES` | Skip episode numbers from the API listing, comma-separated (e.g. `-e 6` or `-e 5,6`). Use when two episodes are combined into one file. |
| `-a SUFFIX EPISODES` | Append a suffix to specific episode filenames, e.g. `-a " (Extended)" 12,18,19` |
| `-q` | Quiet mode: suppress all output except errors |
| `--no-log` | Disable backup log (prevents use of `-z`) |
| `-z` | Undo the most recent rename for the given directory |
| `-v` | Verbose: also show ignored files and search terms |
| `-vv` | Debug: also show directory traversal and API calls |

## Examples

```bash
# Preview renaming the current directory
voca.py -p

# Rename a specific season, specifying the show
voca.py -i 169 -s 2 "/TV/Breaking Bad/Season 02"

# Rename an entire show's library
voca.py "/TV/The Wire"

# Look up a show on TVmaze
voca.py -Q "The Sopranos"

# Undo the last rename
voca.py -z "/TV/Breaking Bad/Season 02"
```

## Supported formats

Video: `.mkv`, `.mp4`, `.avi` — Subtitles: `.srt` (renamed in `subs/` subdirectory if present)

Files of other types in the same directory are skipped and reported.

## Backup and undo

Unless `--no-log` is set, every rename is logged to `~/.local/share/voca/latest.json`. Use `-z` to reverse the most recent rename for a directory.
