import urlparse
import requests
import json
import os
import os.path
import sys
import yaml
import pygit2



GH_TOKEN = os.environ.get('GITHUB_TOKEN', None)
ORG = 'ministryofjustice'
PR_TITLE = 'AUTOGENERATED-add_metadata'
url = 'https://api.github.com/orgs/{0}/repos'.format(ORG)
req_url = 'https://raw.githubusercontent.com/{0}/{1}/{2}/{3}'
pr_url = 'https://api.github.com/repos/{0}/{1}/pulls'
wanted_tag = 'master'
reqs_file = 'formula-requirements.txt'
repos_dir = '/tmp/out123/repos'


def http_creds_callback(*args, **kwargs):
    return pygit2.UserPass(GH_TOKEN, 'x-oauth-basic')


if not os.path.exists(repos_dir):
    os.makedirs(repos_dir, 0755)

if not os.path.exists('/tmp/lala.json'):
    repos = []
    gh_response = requests.get(url, auth=(GH_TOKEN, 'x-oauth-basic'))
    if gh_response.status_code != 200:
        print 'Failed to retrieve repos from github'
        sys.exit(1)

    repos.extend(json.loads(gh_response.text))
    # parse the Link header and extract the number of pages available.
    max_pages = 0
    if 'link' in gh_response.headers:
        for link, rel in map(lambda x: x.split(';'),
                             gh_response.headers['link'].split(',')):
            link = link.strip()[1:-1]
            if rel.split('=')[1] == '"last"':
                try:
                    pg_num = urlparse.urlparse(link).query.split('=')[1]
                    max_pages = int(pg_num)
                except ValueError:
                    pass
                break

    for pg_num in range(2, max_pages+1):
        pg_url = '{0}?page={1}'.format(url, pg_num)
        gh_response = requests.get(pg_url, auth=(GH_TOKEN, 'x-oauth-basic'))
        if gh_response.status_code != 200:
            print 'Failed to retrieve page: {0}'.format(pg_num)
            continue
        repos.extend(json.loads(gh_response.text))
        with open('/tmp/lala.json', 'w') as data:
            json.dump(repos, data)
else:
    with open('/tmp/lala.json') as data:
        repos = json.load(data)

for repo in repos:
    repo_name = repo['name']
    if '-formula' != repo_name[-8:]:
        continue

    # Check if a PR already exists. If a PR exists then there is nothing
    # for us to do here.
    pr = pr_url.format(ORG, repo_name)
    pr_response = requests.get(pr, auth=(GH_TOKEN, 'x-oauth-basic'))
    if pr_response.status_code != 200:
        print '{0}: Cannot access pull requests.'.format(repo_name)
        continue
    pr_titles = [x['title'] for x in json.loads(pr_response.text)]
    if PR_TITLE in pr_titles:
        print '{0}: PR already exists'.format(repo_name)
        continue

    # Is the metadata file already in repo?
    metadata_url = req_url.format(ORG, repo_name, 'metadata', 'metadata.yml')
    metadata_response = requests.get(metadata_url,
                                     auth=(GH_TOKEN, 'x-oauth-basic'))

    # metadata file not found. we need to create and push it to the repo
    if metadata_response.status_code != 200:
        # Generate the requirements list
        reqs_url = req_url.format(ORG, repo_name, wanted_tag, reqs_file)
        reqs_response = requests.get(reqs_url, auth=(GH_TOKEN, 'x-oauth-basic'))
        if reqs_response.status_code == 404:
            print '{0}: No requirements file found.'.format(repo_name)
            continue
        elif reqs_response.status_code != 200:
            print 'Failed to retrieve reqs for repo: {0}.'.format(repo_name)
            continue
        dependencies = []
        for line in reqs_response.text.split('\n'):
            if line:
                dependencies.append(str(line.split('==')[0]))

        # Clone the repository
        repo_dir = os.path.join(repos_dir, repo_name)
        formula_name = repo_name.rsplit('-', 1)[0]
        git_repo = None
        try:
            if os.path.exists(repo_dir):
                git_repo = pygit2.Repository(repo_dir)
            else:
                print 'Cloning %s:' % repo['git_url'],
                git_repo = pygit2.clone_repository(repo['git_url'], repo_dir)
                print 'Done!'
        except pygit2.GitError, e:
            if 'Repository not found' in e.message:
                print 'Repository not found or repository is private'
                continue

        # Create metadata branch unless it already exists.
        if 'refs/remotes/origin/metadata' not in git_repo.listall_references():
            try:
                git_repo.create_branch('metadata', git_repo.head.get_object())
            except ValueError, e:
                pass
            git_repo.checkout('refs/heads/metadata')
        else:
            git_repo.checkout('refs/remotes/origin/metadata')

        with open('{0}/metadata.yml'.format(repo_dir), 'w') as formula_meta:
            out = {'dependencies': dependencies}
            yaml.dump(out, formula_meta, default_flow_style=False)

        git_repo.index.read()
        git_repo.index.add('metadata.yml')
        git_repo.index.write()
        tree = git_repo.index.write_tree()
        sig = pygit2.Signature('Kyriakos Oikonomakos',
                               'kyriakos.oikonomakos@digital.justice.gov.uk')
        parent = git_repo.lookup_reference('HEAD').resolve().get_object().oid
        commit_msg = 'adding metadata.yml'
        oid = git_repo.create_commit('refs/heads/metadata', sig, sig,
                                     commit_msg, tree, [parent])

        remote = git_repo.remotes[0]
        remote.push_url = repo['html_url']
        print remote, remote.push_url
        remote.credentials = http_creds_callback

    pr_data = {'title': 'AUTOGENERATED-add_metadata',
               'head': 'metadata',
               'base': 'master',
               'body': 'Autogenerated PR to include metadata.yml in formula'}

    x = requests.post(pr, data=json.dumps(pr_data),
                      auth=(GH_TOKEN, 'x-oauth-basic'))
    if x.status_code != 201:
        print '{0}: Failed to submit PR.'.format(repo_name)
