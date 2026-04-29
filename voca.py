#!/usr/bin/python3
# coding = utf-8
"""Properly name files of TV episodes using the TVmaze API."""
__author__ = "Chas Kissick"
__license__ = "GNU General Public License v3.0"
__version__ = "0.11"

import os
import sys
import shutil
import argparse
import requests
import json
import itertools
import logging

### TODO:
# add I ignore option that ignores missing episodes (e.g. \
#        if two episodes are combined into one file)
# add log feature
# add "reverse" option
# add try import html2text?
# flesh out "verbose" function, possibly with custom printing function that takes text and priority
# allow for multiple filetypes in the same folder, as long as they are video filetypes

# Parse arguments
parser = argparse.ArgumentParser(description=('Properly name files of TV episodes.'))
parser.add_argument('--query','-q',
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
        action='store_true',
        help='print all files and new names, rather than just changes')
parser.add_argument('--disable_backup','-b',
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
season = args.season if args.season else False
if args.append:
    appender = args.append[0]
    appendees = args.append[1]
else:
    appendees = []
sprompt = False if args.assume_season else True
ignore = args.ignore or []
jumbled = args.jumbled
gentle = args.gentle
preview = args.preview
manual = args.manual
verbose = args.verbose or preview
enable_backup_log = not args.disable_backup
undo_mode = args.undo
wd = args.dir.rstrip('/')

filetypes = ('.mkv','.mp4','.avi','.srt')
LOG_DIR = os.path.expanduser('~/.local/share/voca')
LOG_FILE = os.path.join(LOG_DIR, 'latest.json')

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
        print('No log found. Cannot undo.')
        sys.exit(1)
    except ValueError:
        print('Log file is corrupted.')
        sys.exit(1)
    if directory not in data:
        print('No log entry for: %s' % directory)
        sys.exit(1)
    os.chdir(directory)
    for old, new in data[directory].items():
        if os.path.exists(new):
            if safe_rename(new, old):
                print('\033[37m%s >\n\033[32m%s\033[0m' % (new, old))
        else:
            print('Warning: %s not found, skipping' % new)
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
            print('\033[31m\033[1m''Error: files may not be sorted correctly. '\
                    'Please check:\033[0m')
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
        _episode_cache[showid] = scrape_page(f"https://api.tvmaze.com/shows/{showid}/episodes")
    return _episode_cache[showid]


def get_titles(showid,season):
    titles = []
    for ep in get_episodes(showid):
        if ep['season'] == season:
            titles.append(make_filesafe(ep.get("name") or ""))
    return(titles)


def get_filenames(titles, filetype, old_names=None):
    filenames = []
    if appendees:
        appendeelist = appendees.split(',')
        for appendee in appendeelist:
            appendee = int(appendee)
            titles[appendee-1] = make_filesafe(titles[appendee-1]+appender)
    for i in range(len(titles)):
        ext = filetype if filetype else os.path.splitext(old_names[i])[1]
        filename = '%02d %s%s' % (i+1, make_filesafe(titles[i]), ext)
        filenames.append(filename)
    return filenames


def seasonprompt(folder, missingseasons):
    print('What season is contained in this folder?: %s'%folder)
    while True:
        print('Possible seasons: ',missingseasons)
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
            print('\033[31m\033[1mError: refusing to overwrite existing file:\033[0m %s' % dst)
            return False
    os.rename(src, dst)
    return True

def rename(old_names,filenames,subs_present,old_subnames,subnames):
    if len(old_names) == len(filenames):
        for i in range(len(old_names)):
            if old_names[i] == filenames[i]:
                print(old_names[i]+'- unchanged')
            else:
                print('\033[37m%s >\n\033[32m%s\033[0m'\
                        %(old_names[i],filenames[i]))
                if preview: continue
                else:
                    if not safe_rename(old_names[i],filenames[i]):
                        return 3
        if subs_present:
            os.chdir('subs')
            print('\033[m/subs')
            for i in range(len(old_names)):
                if old_subnames[i] == subnames[i]:
                        print(old_subnames[i]+'- unchanged')
                else:
                    print('\033[37m%s >\n\033[32m%s\033[0m'\
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
                print('Ignoring %s - wrong filetype' % f)
        return (kept, filetype)
    kept = [f for f in files if f.endswith(filetypes)]
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
    retries = 3
    for attempt in range(retries):
        try:
            r = SESSION.get(link, params=params, timeout=10)
            r.raise_for_status()
            return r.json()
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            if attempt < retries - 1:
                print('Timed out, retrying')
                continue
            print('Timed out. Make sure you are online and try again.')
            sys.exit(1)
        except ValueError as e:
            print('Error: API did not return valid JSON.')
            sys.exit(1)
        except requests.exceptions.RequestException as e:
            print('Network/HTTP error. Make sure you are online and try again.')
            print(e)
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
        print('Search term: %s'%searchterm)
        results = scrape_page("https://api.tvmaze.com/search/shows", params={"q":searchterm})
        if bool(results) == False:
            print('\033[31m\033[1mNo search results for term: "%s"!'\
                    %searchterm)
            sys.exit()
        # Grab the score of the first three results and compare them
        choices = []
        scores = []
        for series in results[:3]:
            scores.append(series['score'])
            choices.append(get_show_data(series['show']['id']))
        if not manual and not query and len(choices) == 1:
            choice = choices[0]
        elif not manual and not query and scores[0] > scores[1] + 0.1:
            choice = choices[0]
        else:
            for n in range(len(choices)):
                if query:
                    pass
                else:
                    print('\n\033[1mChoice %d:'%(n+1))
                print_show_data(choices[n],scores[n])
                print('-------------------------------------------------------')
            if query:
                return
            if len(choices) < 3:
                print('No other choices.')
            while True:
                selection = input('Please select 1, 2 or 3, or Q to cancel: ')
                try:
                    choice = choices[int(selection)-1]
                    break
                except ValueError:
                    if selection in ('Q','q','N','n'):
                        print('Quitting.')
                        raise SystemExit
                    else:
                        print('That choice is not valid!')
                except IndexError:
                    print('That choice is not valid!')
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
    print('\033[1m%s\033[0m (id: %s)\
            \n%s\n%s\nPremiere: %s\n%s - %s\
            \n\033[1mSummary: \033[0m%s'
            %(series['series'],series['id'],\
            series['language'],\
            series['genre'],\
            series['premiere'],\
            series['country'],series['network'],\
            series['summary']))
    if score:
        print('Match:%d'%score)


def get_seasons(showid):
    link = 'https://api.tvmaze.com/shows/'+str(showid)+'/seasons'
    seasondata = scrape_page(link)
    totalseasons = list(range(len(seasondata)))
    totalseasons = [i+1 for i in totalseasons]
    return totalseasons


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
    validfiles = 0
    for fil in files:
        if fil.endswith(filetype or filetypes):
            validfiles = 1
            break
    while (not files) or (not files[0].endswith(filetype or filetypes)\
            or (not validfiles)):
        folders = weed_folders(folders)
        if not folders: break
        os.chdir(folders[0])
        path, folders, files = next(os.walk(os.getcwd()))
        for fil in files:
            if fil.endswith(filetype or filetypes):
                validfiles = 1
                break
        print(path)
        levels += 1
# If it contains episodes, process them
    if levels == 0:
        parent = os.path.split(path)[1]
        if parent in ignore:
            print('Ignoring %s'%parent)
            exit()
        if not showid:
            foundshowid = get_showID(parent)
        if not season:
            if parent.lower().startswith('season'):
                foundseason = int(parent[-2:])
            else:
                missingseasons = get_seasons(showid or foundshowid)
                if len(missingseasons) == 1:
                    foundseason = missingseasons[0]
                else:
                    foundseason = seasonprompt(parent,missingseasons)
        print('\033[1m%s\033[0m'%parent)
        execute(path,showid or foundshowid,season or foundseason)
# If it contains seasons, rename the folders and go through each
    elif levels == 1:
        os.chdir('..')
        path, folders, files = next(os.walk(os.getcwd()))
        if not showid:
            foundshowid = get_showID(path)
        missingseasons = get_seasons(showid or foundshowid)
        folders.sort()
        # Count up the seasons to see what is missing before doing anything
        for folder in folders:
            if folder.lower().startswith('season') and len(folder) == 9:
                foundseason = int(folder[-2:])
                missingseasons.remove(foundseason)
        for folder in folders:
            print('\033[1m%s\033[0m'%folder)
            if folder in ignore:
                print('Ignoring %s'%folder)
                continue
            if folder.lower().startswith('season'):
                foundseason = int(folder[-2:])
                if gentle or preview:
                    sd = folder
                else:
                    sd = 'Season %02d'%(foundseason)
                    shutil.move(folder,sd)
                    sd = path+'/'+sd
                execute(sd,showid or foundshowid,foundseason)
            else:
                if sprompt:
                    foundseason = int(seasonprompt(folder, missingseasons))
                if not foundseason:
                    print('Ignoring %s'%folder)
                    continue
                else:
                    missingseasons.remove(foundseason)
                if gentle or preview:
                    sd = folder
                else:
                    sd = 'Season %02d'%(foundseason)
                    shutil.move(folder,sd)
                    sd = path+'/'+sd
                execute(sd,showid or foundshowid,season or foundseason)
# If it contains whole series or greater, recurse through each subfolder:
    elif levels > 1:
        os.chdir(rootpath)
        for folder in rootfolders:
           process_directories(rootpath+'/'+folder) 


def execute(sd,showid,season):
    old_names,ext = get_old_names(sd)
    if not old_names:
        print('No valid files found in this directory! Skipping season.')
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
    if not failure and enable_backup_log:
        log(sd, old_names, filenames)
    else:
        show = get_show_data(showid)
        if failure == 1:
            print('\033[31m\033[1m\nError: More files than episodes! Please '\
                    'verify that the correct series/season is:\033[0m')
            print_show_data(show,None)
        elif failure == 2:
            print('\033[31m\033[1m\nError: Fewer files than episodes! Are you '\
                    'missing data or is the wrong series/season selected? '\
                    '\nOperation canceled. Series:\033[0m')
            print_show_data(show,None)
        elif failure == 3:
            print('\033[31m\033[lm\nError: Rename would overwrite an existing file.'
            '\nOperation canceled for safety.\033[0m')
            print_show_data(show, None)
            return None
        print('\033[1m\nSeason %02d'%season)
        print('Title - File:\033[0m')
        for title,name in itertools.zip_longest(titles,old_names):
            print(title,' - ',name)
        print()

if undo_mode:
    undo(wd)
    print('\033[0mUndo Complete.')
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
        print('\033[0mSimulation Complete.')
    else:
        print('\033[0mOperation Complete.')
