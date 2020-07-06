import os
import sys
import jinja2
import aiohttp_jinja2
import aiohttp_github_helpers as h
from aiohttp import web, ClientSession, BasicAuth, ClientTimeout
from aiohttp_metwork_middlewares import mflog_middleware
from aiohttp_metwork_middlewares import timeout_middleware_factory

DRONE_SERVER = os.environ['DRONE_SERVER']
DRONE_TOKEN = os.environ['DRONE_TOKEN']
TOPICS = ["integration-level-5", "integration-level-4", "integration-level-3",
          "integration-level-2", "integration-level-1"]
ORG = "metwork-framework"
BRANCHES = ["integration", "master", "release_0.8", "release_0.9",
            "release_1.0", "experimental"]
GITHUB_USER = os.environ['GITHUB_USER']
GITHUB_PASS = os.environ['GITHUB_PASS']
TIMEOUT = ClientTimeout(total=20)
AUTH = BasicAuth(GITHUB_USER, GITHUB_PASS)
TEMPLATES_DIR = os.path.join(os.environ['MFSERV_CURRENT_PLUGIN_DIR'], 'main',
                             'templates')
IGNORES = [("mfextaddon_mapserver", "release_0.6"),
           ("mfextaddon_scientific", "release_0.6"),
           ("public-website", "integration"),
           ("docker-drone-docker-specific-image", "integration"),
           ("docker-drone-downstream-specific-image", "integration"),
           ("mflog", "integration"),
           ("docker-mfxxx-centos7-buildimage", "integration"),
           ("docker-mfxxx-centos7-buildimage", "experimental"),
           ("docker-mfxxx-centos7-buildimage", "master"),
           ("docker-mfxxx-centos7-testimage", "integration"),
           ("docker-mfxxx-centos7-testimage", "master"),
           ("docker-mfxxx-centos7-testimage", "experimental")]


async def _drone_get_latest_status(client_session, owner, repo, branch,
                                   page=1):
    url = "%s/api/repos/%s/%s/builds" % (DRONE_SERVER, owner, repo)
    params = {"token": DRONE_TOKEN, "page": page}
    async with client_session.get(url, params=params) as r:
        if r.status != 200:
            return None
        try:
            builds = await r.json()
            if len(builds) == 0:
                return {}
            for build in builds:
                if build['event'] != 'push':
                    continue
                if build['branch'] != branch:
                    continue
                return {"status": build['status'], "number": build['number'],
                        "url": "%s/%s/%s/%i" % (DRONE_SERVER, owner,
                                                repo, build['number'])}
        except Exception:
            return {}
    return None


async def drone_get_latest_status(client_session, owner, repo, branch,
                                  max_page=10):
    page = 1
    while True:
        if page > max_page:
            return None
        status = await _drone_get_latest_status(client_session, owner, repo,
                                                branch, page)
        if status is None:
            page = page + 1
            continue
        if len(status) == 0:
            return None
        else:
            return status


async def handle(request):
    async with ClientSession(auth=AUTH, timeout=TIMEOUT) as session:
        ghrepos = []
        for topic in TOPICS:
            tmp = await h.github_get_org_repos_by_topic(session, ORG, [topic],
                                                        ["testrepo"])
            ghrepos = ghrepos + tmp
        repos = []
        for repo in ghrepos:
            tmp = {"name": repo, "url": "https://github.com/%s/%s" %
                   (ORG, repo), "branches": []}
            for branch in BRANCHES:
                ignored = False
                for ignore in IGNORES:
                    if ignore[0] == repo and ignore[1] == branch:
                        ignored = True
                        break
                if ignored:
                    status_future = None
                else:
                    status_future = drone_get_latest_status(session, ORG, repo,
                                                            branch)
                tmp['branches'].append({
                    "name": branch,
                    "status_future": status_future,
                    "github_link": "https://github.com/%s/%s/tree/%s" %
                    (ORG, repo, branch)
                })
            repos.append(tmp)
        for repo in repos:
            for branch in repo['branches']:
                if branch['status_future'] is None:
                    status = "unknown"
                else:
                    status = await branch['status_future']
                branch['drone_status'] = status
                del(branch['status_future'])
    context = {"REPOS": repos, "BRANCHES": BRANCHES}
    response = aiohttp_jinja2.render_template('home.html', request, context)
    return response


def get_app(timeout=int(os.environ['MFSERV_NGINX_TIMEOUT']) + 2):
    app = web.Application(middlewares=[timeout_middleware_factory(timeout),
                                       mflog_middleware])
    app.router.add_get('/{tail:.*}', handle)
    aiohttp_jinja2.setup(app, loader=jinja2.FileSystemLoader(TEMPLATES_DIR))
    return app


if __name__ == '__main__':
    if len(sys.argv) == 3:
        web.run_app(get_app(int(sys.argv[2])), path=sys.argv[1])
    elif len(sys.argv) == 2:
        web.run_app(get_app(), path=sys.argv[1])
    else:
        web.run_app(get_app())
