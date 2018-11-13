#!/usr/bin/python3
# coding = utf-8
"""Properly name files of TV episodes using the TVmaze API."""
__author__ = "Chas Kissick"
__license__ = "GNU General Public License v3.0"
__version__ = "0.1"

import os
import sys
import shutil
import argparse
import requests
import json
import itertools

### TODO:
# add log feature
# add "reverse" option

# Parse arguments
parser = argparse.ArgumentParser(description='Properly name files of TV \
        episodes.')
parser.add_argument('--showid','-i',
        help='the show ID on tvmaze.com')
parser.add_argument('--link','-l',
        help='the link to the show ID on tvmaze.com or api.tvmaze.com')
parser.add_argument('--filetype','-f',
        nargs='?',
        help='the filetype that the script should look at. By default, the \
                program will search for mkv, mp4 and avi files.')
parser.add_argument('--name','-n',
        help='the exact name of the show to search. Do not include any extra \
                information , e.g. you can use "The Office" but not "The Office\
                 (US)" or "The Office (UK)"')
parser.add_argument('--season','-s',
        type=int,
        help='the season of episodes being edited. Default is determined by the\
                directory name, otherwise asked of the user or assumed to be 1.')
parser.add_argument('--assume_season','-S',
        action='store_true',
        help='Assumes that season folders sorted by alphanumeric order follow \
                the order of the series. Default is to ask the user for each \
                season number before guessing, unless the folder matches the \
                format "Season XX"')
parser.add_argument('--ignore', '-x',
        action='append',
        help='ignores any folder whose name is contained within this string or \
                list of strings (separated by a space). Accepts folder names, \
                not a full path. Example: voca.py -x miniseries webisodes \
                "/TV/Battlestar Galactica"')
parser.add_argument('--gentle', '-g',
        action='store_true',
        help='disables the renaming of any folders')
parser.add_argument('--preview', '-p',
        action='store_true',
        help='preview rename before executing')
parser.add_argument('--manual','-m',
        action='store_true',
        help='force the program to give the user the top three (if available) \
                choices of series before choosing one')
parser.add_argument('--verbose','-v',
        action='store_true',
        help='print all files and new names, rather than just changes')
parser.add_argument('--disable_backup','-b',
        action='store_true',
        help='By default, the program saves logs of old filenames from each \
                folder in the backup directory. Enabling this option \
                makes it impossible to later use the --undo (z) option.')
parser.add_argument('dir',
        nargs='?',
        default=os.getcwd(),
        help='the directory in which the files to be renamed are located. \
                Default is current directory.')
args = parser.parse_args()
showid = args.showid or False
link = args.link or ('http://api.tvmaze.com/shows/'+str(showid)+'/episodes' \
        if showid else False)
filetype = args.filetype
if filetype:
    if not filetype.startswith('.'):
        filetype = '.'+filetype
season = args.season[0] if args.season else False
sprompt = False if args.assume_season else True
ignore = args.ignore or []
gentle = args.gentle
preview = args.preview
manual = args.manual
verbose = args.verbose or preview
wd = args.dir.rstrip('/')

filetypes = ('.mkv','.mp4','.avi')

def get_old_names(directory):
    (_, _,old_names) = next(os.walk(directory)) 
    old_names,ext = weed_files(old_names,filetype)
    try:
        old_names.sort(key=lambda c: int(''.join(filter(str.isdigit, c))))
    except:
        print('\033[31m\033[1m''Error: files may not be sorted correctly. '\
                'Please check:\033[0m')
        old_names.sort()
    return (old_names,ext)


def get_titles(showid,season):
    link = 'http://api.tvmaze.com/shows/'+str(showid)+'/episodes'
    data = scrape_page(link)
    titles = []
    for episode in data:
        if episode['season'] == season:
            title = episode['name']
            filename = ''.join([c if c not in "\/:*?<>|" else '_' \
                    for c in title])
            titles.append(filename)
    return(titles)


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


def rename(old_names,titles,filetype):
    if len(old_names) == len(titles):
#        if reverse:
#            for i in range(0, len(old_names)):
#                os.rename('%s%s%s'%(j,titles[i],filetype), old_names[i])
#                print('%s%s%s'%(j,titles[i],filetype), "=>", old_names[i])
#                if i == len(old_names):
#                    print("Names reverted.")
#                i += 1
#        else:
        for i in range(len(old_names)):
            if old_names[i] == '%02d %s%s'%(i+1,titles[i],filetype):
                print(old_names[i]+'- unchanged')
            else:
                print('\033[37m%s >\n\033[32m%02d %s%s\033[0m'\
                        %(old_names[i],i+1,titles[i],filetype))
                if preview: continue
                else:
                    os.rename(old_names[i], '%02d %s%s'\
                            %(i+1,titles[i],filetype))
        return False
    elif len(old_names) > len(titles):
        return 1
    elif len(old_names) < len(titles):
        return 2


def weed_files(files,filetype):
    for f in files[:]:
        if filetype:
            if f.endswith(filetype):
                pass
            else:
                files.remove(f)
                print('Ignoring %s - wrong filetype'%(f))
        else:
            for ext in filetypes:
                if f.endswith(ext):
                    files,ext = weed_files(files,ext)
                    return (files,ext)
            return False,False
    return (files,filetype)


def weed_folders(directory):
    for d in directory[:]:
        if 'extras' in d.lower() or 'subs' in d.lower():
            directory.remove(d)
        if ignore:
            if len(ignore)>1:
                for x in ignore:
                    if x in d.lower():
                        directory.remove(d)
            else:
                if ignore in d.lower():
                    directory.remove(d)
    directory.sort()
    return directory


def scrape_page(link):
    retry = 3
    try:
        html = requests.get(link)
        data = json.loads(html.content)
    except requests.exceptions.Timeout or requests.exceptions.ConnectionError:
        while retry > 0 and not series:
            print('Timed out, retrying')
            html = requests.get(link)
            data = json.loads(html.content)
            retry -=1
    except requests.exceptions.RequestException as e:
        print('Network error. Make sure you are online and try again.')
        print(e)
        sys.exit()
    return data


def get_showID(directory):
    if link: 
        foundshowid = link.rsplit('/',1)[1]
        return foundshowid
    else:
    # Search using the directory name
        searchterm = os.path.split(directory)[1]
        searchlink = 'http://api.tvmaze.com/search/shows?q=:'+searchterm
        print(searchlink)
        results = scrape_page(searchlink)
        if bool(results) == False:
            print('\n\033[31m\033[1mNo search results for term: "%s"!'\
                    %searchterm)
            sys.exit()
        # Grab the score of the first three results and compare them
        choices = []
        scores = []
        for series in results[:3]:
            scores.append(series['score'])
            choices.append(get_show_data(series['show']['id']))
        if not manual and len(choices) == 1:
            choice = choices[0]
        elif not manual and scores[0]-scores[1] > 10:
            choice = choices[0]
        else:
            for n in range(len(choices)):
                print('\n\033[1mChoice %d:'%(n+1))
                print_show_data(choices[n],scores[n])
                print('-----------------------------')
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
    link = 'http://api.tvmaze.com/shows/'+str(showid)
    print(link)
    series = scrape_page(link)
    data = {'series':series['name'],\
        'language':series['language'],\
        'genre':', '.join(series['genres']) or '- missing data -',\
        'id':series['id'], 'premiere':series['premiered']}
    try:
        data['country'] = series['network']['country']['name']
        data['network'] = series['network']['name']
    # Web shows by e.g. Netflix have no country
    except TypeError:
        data['country'] = 'Online'
        data['network'] = series['webChannel']['name']
    return data


def print_show_data(series,score):
    print('\033[1m%s\033[0m (id: %s)\
            \n%s\n%s\nPremiere: %s\n%s - %s'
            %(series['series'],series['id'],\
            series['language'],\
            series['genre'],\
            series['premiere'],\
            series['country'],series['network']))
    if score:
        print('Match:%d'%score)


def get_seasons(showid):
    link = 'http://api.tvmaze.com/shows/'+str(showid)+'/seasons'
    seasondata = scrape_page(link)
    totalseasons = list(range(len(seasondata)))
    totalseasons = [i+1 for i in totalseasons]
    return totalseasons


def process_directories(root):
    os.chdir(root)
    path, folders, files = next(os.walk(root))
    rootpath = path
    rootfolders = weed_folders(folders)
    files,ext = weed_files(files, filetype)
    if files == False:
        print('No video files found in %s'%(path))
# See how many levels of directories exist until the files, assuming 
# shows/seasons/episodes
    levels = 0
    while (not files) or (not files[0].endswith(filetypes)):
        folders = weed_folders(folders)
        if not folders: return
        os.chdir(folders[0])
        path, folders, files = next(os.walk(os.getcwd()))
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
                foundseason = seasonprompt(parent,missingseasons)
        print('\033[1m%s'%parent)
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
    if len(old_names) == 0:
        print('No valid files found in this directory! Skipping season.')
        return None
    titles = get_titles(showid,season)
    os.chdir(sd)
    failure = rename(old_names,titles,ext)
    os.chdir('..')
    if not failure:
        return None
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
        print('\033[1m\nSeason %02d'%season)
        print('Title - File:\033[0m')
        for title,name in itertools.zip_longest(titles,old_names):
            print(title,' - ',name)
        print()


process_directories(wd)

if preview:
    print('\033[0mSimulation Complete.')
else: print('\033[0mOperation Complete.')
