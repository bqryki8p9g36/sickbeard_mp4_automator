#!/usr/bin/env python3
import os
import sys
import requests
import time
import shutil
from resources.log import getLogger
from resources.readsettings import ReadSettings
from resources.metadata import MediaType
from resources.mediaprocessor import MediaProcessor


def downloadedMoviesScanInProgress(host, port, webroot, apikey, protocol, moviefile_sourcefolder, log):
    headers = {'X-Api-Key': apikey}
    url = protocol + host + ":" + str(port) + webroot + "/api/v3/command"
    log.debug("Requesting list of commands in process")
    r = requests.get(url, headers=headers)
    commands = r.json()
    log.debug(commands)
    log.debug(moviefile_sourcefolder)
    for c in commands:
        if c.get('name') == "DownloadedMoviesScan":
            try:
                if c['body']['path'] == moviefile_sourcefolder and c['state'] == 'started':
                    log.debug("Found a matching path scan in progress %s" % (moviefile_sourcefolder))
                    return True
            except:
                pass
    return False


def rescanAndWait(host, port, webroot, apikey, protocol, movieid, log, retries=6, delay=10):
    headers = {'X-Api-Key': apikey}
    # First trigger rescan
    payload = {'name': 'RescanMovie', 'movieId': movieid}
    url = protocol + host + ":" + str(port) + webroot + "/api/v3/command"
    r = requests.post(url, json=payload, headers=headers)
    rstate = r.json()
    try:
        rstate = rstate[0]
    except:
        pass
    log.debug(str(payload))
    log.debug(str(rstate))
    log.info("Radarr response Rescan command: ID %d %s." % (rstate['id'], rstate['state']))

    # Then wait for it to finish
    url = protocol + host + ":" + str(port) + webroot + "/api/v3/command/" + str(rstate['id'])
    log.info("Requesting command status from Sonarr for command ID %d." % rstate['id'])
    r = requests.get(url, headers=headers)
    command = r.json()
    attempts = 0
    while command['state'].lower() not in ['complete', 'completed'] and attempts < retries:
        log.debug("State: %s." % (command['state']))
        time.sleep(delay)
        r = requests.get(url, headers=headers)
        command = r.json()
        attempts += 1
    log.debug(str(command))
    log.info("Final state: %s." % (command['state']))
    return command['state'].lower() in ['complete', 'completed']


def getMovieInformation(host, port, webroot, apikey, protocol, movieid, log):
    headers = {'X-Api-Key': apikey}
    url = protocol + host + ":" + str(port) + webroot + "/api/v3/movie/" + str(movieid)
    log.info("Requesting updated information from Radarr for movie ID %d." % movieid)
    r = requests.get(url, headers=headers)
    payload = r.json()
    log.debug(str(payload))
    return payload


def getMovieFile(host, port, webroot, apikey, protocol, moviefileid, log):
    headers = {'X-Api-Key': apikey}
    url = protocol + host + ":" + str(port) + webroot + "/api/v3/moviefile/" + str(moviefileid)
    log.info("Requesting information from Radarr for moviefile ID %d." % moviefileid)
    r = requests.get(url, headers=headers)
    payload = r.json()
    return payload


def updateMovieFile(new, host, port, webroot, apikey, protocol, moviefileid, log):
    headers = {'X-Api-Key': apikey}
    url = protocol + host + ":" + str(port) + webroot + "/api/v3/moviefile/" + str(moviefileid)
    log.info("Requesting update from Radarr for moviefile ID %d." % moviefileid)
    r = requests.put(url, json=new, headers=headers)
    payload = r.json()
    return payload


def renameFile(inputfile, log):
    filename, fileext = os.path.splitext(inputfile)
    outputfile = "%s.rnm%s" % (filename, fileext)
    i = 2
    while os.path.isfile(outputfile):
        outputfile = "%s.rnm%d%s" % (filename, i, fileext)
        i += 1
    os.rename(inputfile, outputfile)
    log.debug("Renaming file %s to %s." % (inputfile, outputfile))
    return outputfile


def renameMovie(host, port, webroot, apikey, protocol, movieid, log):
    headers = {'X-Api-Key': apikey}
    # First trigger rescan
    payload = {'name': 'RenameMovie', 'movieIds': [movieid]}
    url = protocol + host + ":" + str(port) + webroot + "/api/command"
    r = requests.post(url, json=payload, headers=headers)
    rstate = r.json()
    try:
        rstate = rstate[0]
    except:
        pass
    log.debug(str(payload))
    log.debug(str(rstate))
    log.info("Radarr response Rename command: ID %d %s." % (rstate['id'], rstate['state']))


def backupSubs(inputpath, mp, log, extension=".backup"):
    dirname, filename = os.path.split(inputpath)
    files = []
    output = {}
    for r, _, f in os.walk(dirname):
        for file in f:
            files.append(os.path.join(r, file))
    for filepath in files:
        if filepath.startswith(os.path.splitext(filename)[0]):
            info = mp.isValidSubtitleSource(filepath)
            if info:
                newpath = filepath + extension
                shutil.copy2(filepath, newpath)
                output[newpath] = filepath
                log.info("Copying %s to %s." % (filepath, newpath))
    return output


def restoreSubs(subs, log):
    for k in subs:
        try:
            os.rename(k, subs[k])
            log.info("Restoring %s to %s." % (k, subs[k]))
        except:
            os.remove(k)
            log.exception("Unable to restore %s, deleting." % (k))


def restoreSceneName(inputfile, scenename):
    if scenename:
        directory = os.path.dirname(inputfile)
        extension = os.path.splitext(inputfile)[1]
        os.rename(inputfile, os.path.join(directory, "%s%s" % (scenename, extension)))


log = getLogger("RadarrPostProcess")

log.info("Radarr extra script post processing started.")

if os.environ.get('radarr_eventtype') == "Test":
    sys.exit(0)

settings = ReadSettings()

log.debug(os.environ)

try:
    inputfile = os.environ.get('radarr_moviefile_path')
    original = os.environ.get('radarr_moviefile_scenename')
    imdbid = os.environ.get('radarr_movie_imdbid')
    tmdbid = os.environ.get('radarr_movie_tmdbid')
    movieid = int(os.environ.get('radarr_movie_id'))
    moviefileid = int(os.environ.get('radarr_moviefile_id'))
    scenename = os.environ.get('radarr_moviefile_scenename')
    releasegroup = os.environ.get('radarr_moviefile_releasegroup')
    moviefile_sourcefolder = os.environ.get('radarr_moviefile_sourcefolder')
except:
    log.exception("Error reading environment variables")
    sys.exit(1)

mp = MediaProcessor(settings)

log.debug("Input file: %s." % inputfile)
log.debug("Original name: %s." % original)
log.debug("IMDB ID: %s." % imdbid)
log.debug("TMDB ID: %s." % tmdbid)
log.debug("Radarr Movie ID: %d." % movieid)

try:
    if settings.Radarr.get('rename'):
        # Prevent asynchronous errors from file name changing
        mp.settings.waitpostprocess = True
        try:
            inputfile = renameFile(inputfile, log)
        except:
            log.exception("Error renaming inputfile")

    success = mp.fullprocess(inputfile, MediaType.Movie, original=original, tmdbid=tmdbid, imdbid=imdbid)

    if success and not settings.Radarr['rescan']:
        log.info("File processed successfully and rescan API update disabled")
    elif success:
        # Update Radarr to continue monitored status
        try:
            host = settings.Radarr['host']
            port = settings.Radarr['port']
            webroot = settings.Radarr['webroot']
            apikey = settings.Radarr['apikey']
            ssl = settings.Radarr['ssl']
            protocol = "https://" if ssl else "http://"

            log.debug("Radarr host: %s." % host)
            log.debug("Radarr port: %s." % port)
            log.debug("Radarr webroot: %s." % webroot)
            log.debug("Radarr apikey: %s." % apikey)
            log.debug("Radarr protocol: %s." % protocol)

            if apikey != '':
                headers = {'X-Api-Key': apikey}

                subs = backupSubs(success[0], mp, log)

                # restoreSceneName(success[0], scenename)

                if downloadedMoviesScanInProgress(host, port, webroot, apikey, protocol, moviefile_sourcefolder, log):
                    log.info("DownloadedMoviesScan command is in process for this movie, cannot wait for rescan but will queue")
                    rescanAndWait(host, port, webroot, apikey, protocol, movieid, log, retries=0)
                    renameMovie(host, port, webroot, apikey, protocol, movieid, log)
                elif rescanAndWait(host, port, webroot, apikey, protocol, movieid, log):
                    log.info("Rescan command completed")

                    movieinfo = getMovieInformation(host, port, webroot, apikey, protocol, movieid, log)
                    if not movieinfo.get('hasFile'):
                        log.warning("Rescanned movie does not have a file, attempting second rescan.")
                        if rescanAndWait(host, port, webroot, apikey, protocol, movieid, log):
                            movieinfo = getMovieInformation(host, port, webroot, apikey, protocol, movieid, log)
                            if not movieinfo.get('hasFile'):
                                log.warning("Rescanned movie still does not have a file, will not set to monitored to prevent endless loop.")
                                sys.exit(1)
                            else:
                                log.info("File found after second rescan.")
                        else:
                            log.error("Rescan command timed out")
                            restoreSubs(subs, log)
                            sys.exit(1)

                    if len(subs) > 0:
                        log.debug("Restoring %d subs and triggering a final rescan." % (len(subs)))
                        restoreSubs(subs, log)
                        rescanAndWait(host, port, webroot, apikey, protocol, movieid, log)

                    movieinfo['monitored'] = True
                    movieinfo['movieFile']['sceneName'] = scenename
                    movieinfo['movieFile']['releaseGroup'] = releasegroup

                    # Then set that movie to monitored
                    log.debug("Sending PUT request with following payload:")
                    log.debug(str(movieinfo))  # debug

                    url = protocol + host + ":" + str(port) + webroot + "/api/movie/" + str(movieid)
                    r = requests.put(url, json=movieinfo, headers=headers)
                    success = r.json()

                    log.debug("PUT request returned:")
                    log.debug(str(success))
                    log.info("Radarr monitoring information updated for movie %s." % success['title'])

                    try:
                        mf = getMovieFile(host, port, webroot, apikey, protocol, movieinfo['movieFile']['id'], log)
                        mf['sceneName'] = scenename
                        mf['releaseGroup'] = releasegroup
                        mf = updateMovieFile(mf, host, port, webroot, apikey, protocol, movieinfo['movieFile']['id'], log)
                        log.debug("Restored releaseGroup to %s." % mf.get('releaseGroup'))
                    except:
                        log.exception("Unable to restore release/scene information")

                    renameMovie(host, port, webroot, apikey, protocol, movieid, log)
                else:
                    log.error("Rescan command timed out")
                    sys.exit(1)
            else:
                log.error("Your Radarr API Key is blank. Update autoProcess.ini to enable status updates.")
        except:
            log.exception("Radarr monitor status update failed.")
    else:
        log.info("Processing returned False.")
        sys.exit(1)
except:
    log.exception("Error processing file")
    sys.exit(1)
