#!/usr/bin/python3
# coding = utf-8
"""Properly name files of TV episodes using the TVmaze API."""
__author__ = "Chas Kissick"
__license__ = "GNU General Public License v3.0"
__version__ = "2026.04.29.7"

import os
import sys
import shutil
import argparse
import requests
import json
import itertools
import re

### TODO:
# TODO #3: handle 429 rate-limit responses from TVmaze with backoff retry
# TODO #4: support season 0 (specials) — currently season=0 is falsy
# TODO #5: strip year/resolution/season suffixes from directory name before searching
# TODO #6: after -p preview, prompt "Execute? [y/N]" instead of requiring a second run
# TODO #7: remove -j flag; replace sort with natural sort (splits text/number segments)
#           so files like 1.mkv, 2.mkv, 10.mkv always sort correctly without a flag
# TODO #8: quiet mode + get_showID() manual selection — show choices even with -q
# TODO #9: .vocaignore file — a file placed in a folder (or its parent) that lists
#           subdirectory names to skip, as an alternative to repeating -x on the CLI

# Parse arguments
parser = argparse.ArgumentParser(description=('Properly name files of TV episodes.'))
parser.add_argument('--query','-Q',
        action='store_true',
        help=('Queries the database for show info if a number is input, otherwise queries the database with the search term.'))
parser.add_argument('--showid','-i',
        help='the show ID on tvmaze.com')
parser.add_argument('--link','-l',
        help='the link to the show ID on tvmaze.com or api.tvmaze.com')
parser.add_argument('--filetype','-f',
        nargs='?',
        help=(
            'the filetype that the script should look at. By default, the '
            'program will search for mkv, mp4 and avi files.'))
parser.add_argument('--name','-n',
        help=(
            'the exact name of the show to search. Do not include any extra '
            'information , e.g. you can use "The Office" but not "The Office '
            '(US)" or "The Office (UK)"'))
parser.add_argument('--season','-s',
        type=int,
        help=(
            'the season of episodes being edited. Default is determined by the '
            'directory name, otherwise prompted for  or assumed to be 1.'))
parser.add_argument('--append','-a',
        nargs=2,
        help=(
            'append a word to certain episode titles. '
            '\nExample: voca.py -a " (Extended) 12,18,19" will add '
            '" (Extended)" to the end of the filenames of episodes '
            '12, 18 and 19.'))
parser.add_argument('--assume_season','-S',
        action='store_true',
        help=(
            'Assumes that season folders sorted by alphanumeric order follow '
            'the order of the series. Default is to ask the user for each '
            'season number before guessing, unless the folder matches the '
            'format "Season XX"'))
parser.add_argument('--ignore', '-x',
        action='append',
        help=(
            'ignores any folder whose name is contained within this string or '
            'list of strings (separated by a space). Accepts folder names, '
            'not a full path. Example: voca.py -x miniseries webisodes '
            '"/TV/Battlestar Galactica"'))
parser.add_argument('--jumbled','-j',
        action='store_true',
        help='if files are not in alphabetical order, tries to sort by number')
parser.add_argument('--gentle', '-g',
        action='store_true',
        help='disables the renaming of any folders')
parser.add_argument('--preview', '-p',
        action='store_true',
        help='preview rename before executing')
parser.add_argument('--manual','-m',
        action='store_true',
        help=(
            'force the program to give the user the top three (if available) '
            'choices of series before choosing one'))
parser.add_argument('--verbose','-v',
        action='count',
        default=0,
        help='-v: verbose output (ignored files, search terms); -vv: debug (directory progress, API calls)')
parser.add_argument('--skip','-e',
        help='episode numbers to skip from the API listing, comma-separated (e.g. -e 6 or -e 5,6)')
parser.add_argument('--quiet','-q',
        action='store_true',
        help='suppress all output except errors')
parser.add_argument('--no-log',
        action='store_true',
        help=(
            'By default, the program saves logs of old filenames from each '
            'folder in the backup directory. Enabling this option '
            'makes it impossible to later use the --undo (z) option.'))
parser.add_argument('--undo','-z',
        action='store_true',
        help='undo the most recent rename operation for the given directory')
parser.add_argument('dir',
        nargs='?',
        default=os.getcwd(),
        help=(
            'The directory in which the files to be renamed are located. '
            'Default is current directory.'))
args = parser.parse_args()
query = args.query
showid = args.showid or False
link = args.link or ('https://api.tvmaze.com/shows/'+str(showid)+'/episodes' \
        if showid else False)
filetype = args.filetype
SESSION = requests.Session()

if filetype:
    if not filetype.startswith('.'):
        filetype = '.'+filetype
name = args.name if args.name else False
# None = not specified (so season 0 / specials remains a valid explicit choice)
season = args.season
if args.append:
    appender = args.append[0]
    appendees = args.append[1]
else:
    appendees = []
sprompt = False if args.assume_season else True
ignore = args.ignore or []
skip_episodes = set(int(x) for x in args.skip.split(',')) if args.skip else set()
jumbled = args.jumbled
gentle = args.gentle
preview = args.preview
manual = args.manual
verbosity = args.verbose
quiet_mode = args.quiet
enable_backup_log = not args.no_log
undo_mode = args.undo
wd = args.dir.rstrip('/')

filetypes = ('.mkv','.mp4','.avi','.srt')
LOG_DIR = os.path.expanduser('~/.local/share/voca')
LOG_FILE = os.path.join(LOG_DIR, 'latest.json')

def vprint(text, priority=1):
    """Priority: 0=always (errors), 1=normal, 2=verbose (-v), 3=debug (-vv)."""
    if priority == 0 or (not quiet_mode and priority <= verbosity + 1):
        print(text)


def log(directory, old_names, filenames):
    os.makedirs(LOG_DIR, exist_ok=True)
    try:
        with open(LOG_FILE, 'r') as f:
            data = json.load(f)
    except (FileNotFoundError, ValueError):
        data = {}
    data[directory] = dict(zip(old_names, filenames))
    with open(LOG_FILE, 'w') as f:
        json.dump(data, f, indent=2)


def undo(directory):
    try:
        with open(LOG_FILE, 'r') as f:
            data = json.load(f)
    except FileNotFoundError:
        vprint('No log found. Cannot undo.', 0)
        sys.exit(1)
    except ValueError:
        vprint('Log file is corrupted.', 0)
        sys.exit(1)
    if directory not in data:
        vprint('No log entry for: %s' % directory, 0)
        sys.exit(1)
    os.chdir(directory)
    for old, new in data[directory].items():
        if os.path.exists(new):
            if safe_rename(new, old):
                vprint('\033[37m%s >\n\033[32m%s\033[0m' % (new, old))
        else:
            vprint('Warning: %s not found, skipping' % new, 0)
    del data[directory]
    with open(LOG_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def get_old_names(directory):
    (_, _,old_names) = next(os.walk(directory))
    old_names,ext = weed_files(old_names,filetype)
    if jumbled:
        try:
            old_names.sort(key=lambda c: int(''.join(filter(str.isdigit, c))))
        except:
            vprint('\033[31m\033[1mError: files may not be sorted correctly. '\
                    'Please check:\033[0m', 0)
    else:
        old_names.sort()
    return (old_names,ext)

_episode_cache = {}


def make_filesafe(name, replacement='_', max_len=240):
    """
    Convert an arbitrary string into a filename-safe component.
    - Replaces common forbidden characters with replacement.
    - Strips control characters.
    - Collapses whitespace.
    - Avoids trailing spaces/dots (Windows-hostile).
    - Enforces a conservative max length (keeps room for prefix/extension).
    """
    if name is None:
        name = ''
    name = str(name)
    # Collapse internal whitespace to single spaces
    name = ' '.join(name.split())
    # Common forbidden filename chars (Windows set; safe superset for most cases)
    forbidden = '\\/:*?"<>|'
    out = []
    for ch in name:
        # Drop NUL and other control characters
        if ch == '\0' or ord(ch) < 32:
            continue
        out.append(replacement if ch in forbidden else ch)

    name = ''.join(out).strip(' .')
    if not name:
        name = 'Untitled'
    if len(name) > max_len:
        name = name[:max_len].rstrip(' .')
    return name


def get_episodes(showid):
    if showid not in _episode_cache:
        vprint('Fetching episodes for show ID %s' % showid, 3)
        _episode_cache[showid] = scrape_page(f"https://api.tvmaze.com/shows/{showid}/episodes")
    else:
        vprint('Using cached episodes for show ID %s' % showid, 3)
    return _episode_cache[showid]


def get_titles(showid,season):
    titles = []
    for ep in get_episodes(showid):
        if ep['season'] == season and ep['number'] not in skip_episodes:
            titles.append(make_filesafe(ep.get("name") or ""))
    return(titles)


def get_filenames(titles, filetype, old_names=None):
    # Work on a copy so the caller's list isn't mutated (it's reused for the
    # error summary and for a second call when subtitles are present).
    titles = list(titles)
    if appendees:
        for appendee in appendees.split(','):
            idx = int(appendee) - 1
            titles[idx] = make_filesafe(titles[idx] + appender)
    filenames = []
    for i in range(len(titles)):
        ext = filetype if filetype else os.path.splitext(old_names[i])[1]
        filenames.append('%02d %s%s' % (i+1, make_filesafe(titles[i]), ext))
    return filenames


def seasonprompt(folder, missingseasons):
    print('What season is contained in this folder?: %s'%folder)
    while True:
        print('Possible seasons: %s' % missingseasons)
        season = input('Enter an integer from the above selection '\
                'or type Q to ignore this directory: ')
        try:
            season = int(season)
        except ValueError:
            if season in ('Q','q','N','n'):
                return False
            else:
                pass
        if season in missingseasons:
            break
        else:
            print('That choice is not valid!')
            pass
    return season

def safe_rename(src, dst):
    # Refuse to overwrite an existing destination
    if os.path.exists(dst):
            vprint('\033[31m\033[1mError: refusing to overwrite existing file:\033[0m %s' % dst, 0)
            return False
    os.rename(src, dst)
    return True

def rename(old_names,filenames,subs_present,old_subnames,subnames):
    if len(old_names) == len(filenames):
        for i in range(len(old_names)):
            if old_names[i] == filenames[i]:
                vprint(old_names[i]+'- unchanged')
            else:
                vprint('\033[37m%s >\n\033[32m%s\033[0m'\
                        %(old_names[i],filenames[i]))
                if preview: continue
                else:
                    if not safe_rename(old_names[i],filenames[i]):
                        return 3
        if subs_present:
            os.chdir('subs')
            vprint('\033[m/subs')
            for i in range(len(old_names)):
                if old_subnames[i] == subnames[i]:
                        vprint(old_subnames[i]+'- unchanged')
                else:
                    vprint('\033[37m%s >\n\033[32m%s\033[0m'\
                            %(old_subnames[i],subnames[i]))
                    if preview: continue
                    else:
                        if not safe_rename(old_subnames[i],subnames[i]):
                            return 3
            subs_present = False
            os.chdir('..')
        return False
    elif len(old_names) > len(filenames):
        return 1
    elif len(old_names) < len(filenames):
        return 2


def weed_files(files, filetype):
    if filetype:
        kept = [f for f in files if f.endswith(filetype)]
        for f in files:
            if not f.endswith(filetype):
                vprint('Ignoring %s - not a supported video file' % f, 2)
        return (kept, filetype)
    kept = [f for f in files if f.endswith(filetypes)]
    for f in files:
        if not f.endswith(filetypes):
            vprint('Ignoring %s - not a supported video file' % f, 2)
    if not kept:
        return [], None
    exts = {os.path.splitext(f)[1] for f in kept}
    return (kept, exts.pop() if len(exts) == 1 else None)


def weed_folders(folders):
    out = []
    for d in folders:
        dl = d.lower()
        if 'extras' in dl or 'subs' in dl:
            continue
        out.append(d)
    out.sort()
    return out


def scrape_page(link, params=None):
    vprint('API call: %s%s' % (link, ' %s' % params if params else ''), 3)
    retries = 3
    for attempt in range(retries):
        try:
            r = SESSION.get(link, params=params, timeout=10)
            r.raise_for_status()
            return r.json()
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            if attempt < retries - 1:
                vprint('Timed out, retrying', 2)
                continue
            vprint('Timed out. Make sure you are online and try again.', 0)
            sys.exit(1)
        except ValueError as e:
            vprint('Error: API did not return valid JSON.', 0)
            sys.exit(1)
        except requests.exceptions.RequestException as e:
            vprint('Network/HTTP error. Make sure you are online and try again.', 0)
            vprint(str(e), 0)
            sys.exit(1)


def get_showID(directory):
    if link: 
        foundshowid = link.rsplit('/',1)[1]
        return foundshowid
    else:
    # Search using the directory name
        if name:
            searchterm = name
        else:
            searchterm = os.path.split(directory)[1]
        vprint('Search term: %s'%searchterm, 2)
        results = scrape_page("https://api.tvmaze.com/search/shows", params={"q":searchterm})
        if bool(results) == False:
            vprint('\033[31m\033[1mNo search results for term: "%s"!'\
                    %searchterm, 0)
            sys.exit()
        # Compare the scores of the top three results. The search response
        # already embeds each show, so we only fetch full details (an extra
        # API call per show) when we actually need to display the choices.
        results = results[:3]
        scores = [series['score'] for series in results]
        shows = [series['show'] for series in results]
        auto = not manual and not query and (
                len(shows) == 1 or scores[0] > scores[1] + 0.1)
        if auto:
            return shows[0]['id']
        choices = [get_show_data(show['id']) for show in shows]
        for n in range(len(choices)):
            if not query:
                vprint('\n\033[1mChoice %d:'%(n+1))
            print_show_data(choices[n],scores[n])
            vprint('-------------------------------------------------------')
        if query:
            return
        if len(choices) < 3:
            vprint('No other choices.', 2)
        while True:
            selection = input('Please select 1, 2 or 3, or Q to cancel: ')
            try:
                choice = choices[int(selection)-1]
                break
            except ValueError:
                if selection in ('Q','q','N','n'):
                    vprint('Quitting.')
                    raise SystemExit
                else:
                    vprint('That choice is not valid!')
            except IndexError:
                vprint('That choice is not valid!')
                pass
        showid = choice['id']
    return showid


def get_show_data(showid):
    link = 'https://api.tvmaze.com/shows/'+str(showid)
    #print(link)
    series = scrape_page(link)
    data = {'series':series['name'],\
        'language':series['language'],\
        'genre':', '.join(series['genres']) or '- missing data -',\
        'id':series['id'], 'premiere':series['premiered']}
    # Web shows by e.g. Netflix have no country
    try:
        data['country'] = series['network']['country']['name']
        data['network'] = series['network']['name']
    except TypeError:
        data['country'] = 'Online'
        data['network'] = series['webChannel']['name']
    summ = series['summary']
    if(summ):
        while '<p>' in summ:
            summ = summ.replace('<p>','')
            summ = summ.replace('</p>','\n')
        while '<b>' in summ:
            summ = summ.replace('<b>','\033[1m')
            summ = summ.replace('</b>','\033[0m')
        summ = summ.replace('&nbsp;',' ')
        summ = summ.replace('&amp;','&')
        #while '<' in summ or '>' in summ:
        #    summ = summ.replace(summ[summ.find('<'):summ.find('>')+1],'')
        data['summary'] = summ
    else:
        data['summary'] = "No summary available"
    return data


def print_show_data(series,score):
    vprint('\033[1m%s\033[0m (id: %s)\
            \n%s\n%s\nPremiere: %s\n%s - %s\
            \n\033[1mSummary: \033[0m%s'
            %(series['series'],series['id'],\
            series['language'],\
            series['genre'],\
            series['premiere'],\
            series['country'],series['network'],\
            series['summary']))
    if score:
        vprint('Match:%d'%score)


def get_seasons(showid):
    link = 'https://api.tvmaze.com/shows/'+str(showid)+'/seasons'
    seasondata = scrape_page(link)
    return list(range(1, len(seasondata) + 1))


def parse_season(folder):
    """Extract a season number from a folder named like 'Season 1',
    'Season 02' or 'Season 100'. Returns an int, or None if it doesn't
    look like a season folder."""
    if not folder.lower().startswith('season'):
        return None
    match = re.search(r'(\d+)', folder)
    return int(match.group(1)) if match else None


def process_directories(root):
    os.chdir(root)
    root = os.getcwd()
    path, folders, files = next(os.walk(root))
    rootpath = path
    rootfolders = weed_folders(folders)
#    files,ext = weed_files(files, filetype)
#    if files == False:
#        print('No video files found in %s'%(path))
# See how many levels of directories exist until the files, assuming 
# shows/seasons/episodes
    levels = 0
    exts = filetype or filetypes
    validfiles = any(fil.endswith(exts) for fil in files)
    while not validfiles:
        folders = weed_folders(folders)
        if not folders: break
        os.chdir(folders[0])
        path, folders, files = next(os.walk(os.getcwd()))
        validfiles = any(fil.endswith(exts) for fil in files)
        vprint(path, 3)
        levels += 1
# If it contains episodes, process them
    if levels == 0:
        parent = os.path.split(path)[1]
        if parent in ignore:
            vprint('Ignoring %s'%parent)
            exit()
        if not showid:
            foundshowid = get_showID(parent)
        foundseason = season
        if foundseason is None:
            foundseason = parse_season(parent)
        if foundseason is None:
            missingseasons = get_seasons(showid or foundshowid)
            if len(missingseasons) == 1:
                foundseason = missingseasons[0]
            else:
                foundseason = seasonprompt(parent,missingseasons)
        if foundseason is False:
            vprint('Ignoring %s'%parent)
            return
        vprint('\033[1m%s\033[0m'%parent)
        execute(path,showid or foundshowid,foundseason)
# If it contains seasons, rename the folders and go through each
    elif levels == 1:
        os.chdir('..')
        path, folders, files = next(os.walk(os.getcwd()))
        if not showid:
            foundshowid = get_showID(path)
        missingseasons = get_seasons(showid or foundshowid)
        folders = weed_folders(folders)
        # Count up the seasons to see what is missing before doing anything
        for folder in folders:
            num = parse_season(folder)
            if num is not None and num in missingseasons:
                missingseasons.remove(num)
        for folder in folders:
            vprint('\033[1m%s\033[0m'%folder)
            if folder in ignore:
                vprint('Ignoring %s'%folder)
                continue
            foundseason = parse_season(folder)
            if foundseason is None:
                # Not a "Season NN" folder: ask, or with -S/--assume_season
                # take the next missing season in alphanumeric order.
                if sprompt:
                    foundseason = seasonprompt(folder, missingseasons)
                elif missingseasons:
                    foundseason = missingseasons[0]
                else:
                    foundseason = False
                if foundseason is False:
                    vprint('Ignoring %s'%folder)
                    continue
                if foundseason in missingseasons:
                    missingseasons.remove(foundseason)
            if gentle or preview:
                sd = folder
            else:
                sd = 'Season %02d'%(foundseason)
                shutil.move(folder,sd)
                sd = path+'/'+sd
            execute(sd,showid or foundshowid,foundseason)
# If it contains whole series or greater, recurse through each subfolder:
    elif levels > 1:
        os.chdir(rootpath)
        for folder in rootfolders:
           process_directories(rootpath+'/'+folder) 


def execute(sd,showid,season):
    old_names,ext = get_old_names(sd)
    if not old_names:
        vprint('No valid files found in this directory! Skipping season.', 0)
        return None
    titles = get_titles(showid,season)
    filenames = get_filenames(titles, ext, old_names)
    subs_present = False
    old_subnames = []
    subnames = []
    if os.path.exists(sd+'/subs/'):
        old_subnames,subext = get_old_names(sd+'/subs/')
        if old_subnames and subext:
            subs_present = True
            subnames = get_filenames(titles, subext, old_subnames)
        else:
            subs_present = False
    os.chdir(sd)
    failure = rename(old_names,filenames,subs_present,old_subnames,subnames)
    os.chdir('..')
    if not failure:
        if enable_backup_log and not preview:
            log(sd, old_names, filenames)
    else:
        show = get_show_data(showid)
        if failure == 1:
            vprint('\033[31m\033[1m\nError: More files than episodes! Please '\
                    'verify that the correct series/season is:\033[0m', 0)
            print_show_data(show,None)
        elif failure == 2:
            vprint('\033[31m\033[1m\nError: Fewer files than episodes! Are you '\
                    'missing data or is the wrong series/season selected? '\
                    '\nOperation canceled. Series:\033[0m', 0)
            print_show_data(show,None)
        elif failure == 3:
            vprint('\033[31m\033[1m\nError: Rename would overwrite an existing file.'
            '\nOperation canceled for safety.\033[0m', 0)
            print_show_data(show, None)
            return None
        vprint('\033[1m\nSeason %02d'%season, 0)
        vprint('Title - File:\033[0m', 0)
        for title,name in itertools.zip_longest(titles,old_names):
            vprint('%s  -  %s' % (title, name), 0)
        vprint('', 0)

if undo_mode:
    undo(wd)
    vprint('\033[0mUndo Complete.')
elif query:
    try:
        wd = int(wd)
        data = get_show_data(wd)
        print_show_data(data, None)
    except ValueError:
        get_showID(wd)
else:
    process_directories(wd)
    if preview:
        vprint('\033[0mSimulation Complete.')
    else:
        vprint('\033[0mOperation Complete.')
