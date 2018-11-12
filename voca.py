#!/usr/bin/python
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
# Complete implementation of missingseasons
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
        default='.mkv',
        help='the filetype that the script should look at. Default is mkv.')
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
                season number before guessing, \
                unless the folder follows the naming convention "Season XX"')
parser.add_argument('--ignore', '-x',
        nargs='?',
        help='ignores any folder whose name is contained within this string or \
                list of strings (separated by a space). Accepts folder names, \
                not a full path. Example: voca.py -x miniseries webisodes \
                "/TV/Battlestar Galactica"')
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
season = args.season[0] if args.season else False
sprompt = False if args.assume_season else True
ignore = args.ignore or []
preview = args.preview
manual = args.manual
verbose = args.verbose or preview
wd = args.dir.rstrip('/')

filetypes = ('.mkv','.mp4','.avi')

def get_old_names(directory):
    old_names = os.listdir(directory)
    old_names.sort()
    weed_files(old_names,filetype)
    return old_names 


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
    print('Possible seasons: ',missingseasons)
    while True:
        season = input('\nPlease enter an integer from the above selection: ')
        try:
            season = int(season)
            break
        except ValueError:
            pass
    return season


def rename(old_names,titles):
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
                    print(os.getcwd())
                    os.rename(old_names[i], '%02d %s%s'\
                            %(i+1,titles[i],filetype))
            i += 1
        return False
    elif len(old_names) > len(titles):
        return 1
    elif len(old_names) < len(titles):
        return 2


def weed_files(files,filetype):
    for f in files[:]:
        if f.endswith(filetype):
            pass
        else:
            files.remove(f)
            print('Ignoring %s'%(f))
    return files


def weed_folders(directory):
    for d in directory[:]:
        if 'extras' in d.lower() or 'subs' in d.lower():
            directory.remove(folder)
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
        print(e)
        sys.exit()
    return data


def get_showID(directory):
    if link: 
        foundshowid = link.rsplit('/',1)[1]
        return foundshowid
    else:
    # Search using the directory name
        searchterm = os.path.split(wd)[1]
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
                print('\n\033[1mChoice %d: \n%s\033[0m\
                        \n%s\n%s\n%s - %s\nMatch:%d\n-------------------'\
                        %(n+1,choices[n]['series'],\
                        choices[n]['language'],\
                        choices[n]['genre'],\
                        choices[n]['country'],choices[n]['network'],
                        scores[n]))
                if len(choices) < 3:
                    print('No other choices.')
            selection = input("Please select 1, 2 or 3, or Q to cancel: ")
            if selection in ('Q','q','N','n'):
                raise SystemExit
            else:
                choice = choices[int(selection)-1]
        showid = choice['id']
    return showid


def get_show_data(showid):
    link = 'http://api.tvmaze.com/shows/'+str(showid)
    print(link)
    series = scrape_page(link)
    data = {'series':series['name'],\
        'language':series['language'],\
        'genre':', '.join(series['genres']) or '- missing data -',\
        'id':series['id']}
    try:
        data['country'] = series['network']['country']['name']
        data['network'] = series['network']['name']
    # Web shows by e.g. Netflix have no country
    except TypeError:
        data['country'] = 'Online'
        data['network'] = series['webChannel']['name']
    return data


def get_seasons(showid)
    link = 'http://api.tvmaze.com/shows/'+str(showid)+'/seasons'
    seasondata = scrape_page(link)
    totalseasons = list(range(len(totalseasons)))
    totalseasons = [i+1 for i in missingseasons]
    return total

def process_directories(root):
    os.chdir (root)
    path, folders, files = next(os.walk(root))
    weed_files(files, filetype)
# See how many levels of directories exist until the files, assuming 
# shows/seasons/episodes
    levels = 0
    while (not files) or (not files[0].endswith(filetypes)):
        folders = weed_folders(folders)
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
                foundseason = seasonprompt(parent)
        print(parent)
        execute(path,showid or foundshowid,season or foundseason)
# If it contains seasons, rename the folders and go through each
    elif levels == 1:
        os.chdir('..')
        path, folders, files = next(os.walk(os.getcwd()))
        if not showid:
            foundshowid = get_showID(path)
        missingseasons = get_seasons(showid or foundshowid)
        folders.sort()
        for folder in folders:
            if folder.lower().startswith('season') and len(folder) == 9:
                madeseason = int(folder[-2:])+1
                missingseasons.remove(madeseason)
        for folder in folders:
            print(folder)
            if folder in ignore:
                print('Ignoring %s'%folder)
                continue
            if folder.lower().startswith('season'):
                foundseason = int(folder[-2:])
                sd = folder
                execute(sd,showid or foundshowid,foundseason)
                os.chdir('..')
            else:
                if sprompt:
                    foundseason = seasonprompt(folder, missingseasons)
                sd = 'Season %02d'%(foundseason or madeseason) 
                shutil.move(folder,sd)
                sd = path+'/'+sd
                execute(sd,showid or foundshowid,season)
                os.chdir('..')
                madeseason += 1
# If it contains whole series or greater, recurse through each subfolder:
    elif levels > 1:
        for folder in folders:
           process_directories(folder) 


def execute(sd,showid,season):
    old_names = get_old_names(sd)
    titles = get_titles(showid,season)
    os.chdir(sd)
    failure = rename(old_names,titles)
    if not failure:
        return None
    else:
        show = get_show_data(showid)
        if failure == 1:
            print('\033[31m\033[1m\nError: More files than episodes! Please '\
                    'verify that the correct series/season is: \n'
                    '\033[0m\033[1m%s\n\033[0m%s\n%s\n%s - %s'\
                    %(show['series'],show['language'],show['genre'],\
                    show.get('country'),show['network']))
            print('\nSeason %02d'%season)
            print('\033[1m\nTitle - File:\033[0m')
            for title,name in itertools.zip_longest(titles,old_names):
                print(title,' - ',name)
        elif failure == 2:
            print('\033[31m\033[1m\nError: Fewer files than episodes! Are you '\
                    'missing data or is the wrong series/season selected? '\
                    '\nOperation canceled. Series: \n'
                    '\033[0m\033[1m%s\n\033[0m%s\n%s\n%s - %s'\
                    %(show['series'],show['language'],show['genre'],\
                    show.get('country'),show['network']))
            print('\nSeason %02d'%season)
            print('\033[1m\nTitle - File:\033[0m')
            for title,name in itertools.zip_longest(titles,old_names):
                print(title,' - ',name)


process_directories(wd)

if preview:
    print('\033[0m\nSimulation Complete.')
else: print('\033[0m\nOperation Complete.')
