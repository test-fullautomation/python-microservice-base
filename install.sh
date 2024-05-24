#!/bin/sh

set -o errexit
set -o nounset
set -o pipefail

# URLs for the repositories
BASE_SERVICE=https://github.com/test-fullautomation/python-microservice-base
CLEWARE_SERVICE=https://github.com/test-fullautomation/python-microservice-cleware-switch


function logresult(){
	if [ "$1" -eq 0 ]; then
	    echo -e "\e[32mSuccessfully $2\e[0m"
	else
		echo -e "\e[31mSuccessfully $2\e[0m"
	fi
}

create_repos_directory() {
  local repos_dir='./repos'

  echo "Creating repos directory for all DevAtServ service..."

  if [[ -e $repos_dir ]]; then
    echo "     Directory $repos_dir already exists. Updating clone."
  else
    mkdir -p "$repos_dir" || return
  fi

  cd "$repos_dir" || return 1
}


start_docker_compose() {
  echo "Starting the DevArtServ Docker containers"

  if ! docker compose >/dev/null 2>&1; then
    echo "failed to find 'docker compose'"
    exit 1
  fi

  if ! docker compose up --remove-orphans -d; then
    echo "Could not start. Check for errors above."
    exit 1
  fi
}

# Clone or update repository
# Arguments:
#	$repo_path : location to clone repo into
#	$repo_url  : repo url
#	$commit_branch_tag  : target commit, branch or tag to point to
function clone_update_repo () {
	repo_path=$1
	repo_url=$2
	commit_branch_tag=$3

	# 1. Check is repo folder is existing or not
	# 2. Ensure the repo url is correct
	# 3. Fetch all from git server
	# 4. Discard all user changes includes untracked files
	# 5. Ensure the default branch change (from git server)
	# 6. Checkout to target branch/commit/tag
	# 7. Ensure branch/commit/tag is up-to-date with remote

	if [ -d "$repo_path" ]; then
		echo "Cleaning and updating repo $repo_path"

		current_url=$(git -C "$repo_path" remote get-url origin)
		if [ "$current_url" != "$repo_url" ]; then
			echo "Repo URL has changed, update remote origin to ${repo_url}"
			git -C "$repo_path" remote set-url origin "$repo_url"
		fi

		git -C "$repo_path" fetch --all
		echo "Clean all local changes/commits"
		git -C "$repo_path" reset --hard HEAD
		git -C "$repo_path" clean -f -d -x

		if [ -z "$commit_branch_tag" ]; then
			default_branch=$(git -C "$repo_path" remote show origin | grep "HEAD branch" | cut -d " " -f 5)
			echo "Default branch: $default_branch"
			git -C "$repo_path" checkout $default_branch
			git -C "$repo_path" reset --hard origin/$default_branch
			logresult "$?" "switched to '$default_branch'" "checkout to '$default_branch' from '$repo_url'"
		fi

		# try to remove existing directory and clone repo again
		if [ "$?" -ne 0 ]; then
			echo "Cloning $repo_url again"
			rm -rf "$repo_path"
			git clone "$repo_url" "$repo_path"
		fi
	else
		echo "Cloning $repo_url"
		git clone "$repo_url" "$repo_path"
	fi
	if [ "$?" -ne 0 ]; then
		exit 1
	fi

	if [ -n "$commit_branch_tag" ]; then
		echo "Checking out to '$commit_branch_tag'"
		git -C "$repo_path" checkout $commit_branch_tag
		if [ "$?" -ne 0 ]; then
			errormsg	"Given tag/branch '$commit_branch_tag' is not existing" 
		fi
		git -C "$repo_path" pull origin $commit_branch_tag
		logresult "$?" "switched to '$commit_branch_tag'" "checkout to '$commit_branch_tag' from '$repo_url'"
	fi
}



#
main() {
	echo -e "\e[33mStarting DevArtServ inslallation...\e[0m"
	create_repos_directory || {
		echo 'error creating repos directory' 
		return 1
	}

	clone_update_repo ../repos/python-microservice-base $BASE_SERVICE "htv3hc/feat/dockerize-microservice-base"
	clone_update_repo ../repos/python-microservice-cleware-switch $CLEWARE_SERVICE "htv3hc/feat/dockerize-cleware-service"

	# Build and start the services
	start_docker_compose || {
		echo 'error starting Docker' 
		return 1
	}

	echo -e "\e[33mAll services are running...\e[0m"
	return 0 
}


main
Exit=$?
if [ $Exit != 0 ]; then
	echo "Can't not install DevArtServ successfully..."

