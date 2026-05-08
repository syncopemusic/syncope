# Syncope
Songs and singers participation tracker

## Requirements

- uv 0.11+

## Installation

Minimal settings to run the app locally:

1. Create your own `.env` file; there is `.env.example` for trying out
2. Edit `.env` file, generate a new 32-character secret key and put it in the
   "your-secret-key-here-generate-new-one"
3. `uv sync`
4. `uv run manage.py migrate`
5. `uv run manage.py loaddata syncope/fixtures/syncope/*.json`
6. `uv run manage.py runserver`

Congratulations, this is now running!

### Docker

Coming soon.

## Usage

Firstly register yourself and create your own organization. Organization is the center of the app.

### Managing persons

Your persons are destined to four roles:

- admins for overviewing the application
- members that actively participate in your activities
- supporters that do not actively participate but contribute in other ways
- external - every person that is not active within your organization

Every change of the role has its own period of activity. 
One can have more than one role at the same time, but only once per organization.



### Managing songs

Step one is make your composer and poet persons into your organization.
Next you add a song and you have to assign it to the composer and poet persons.

- Lyrics are optional, translations as well, each text can be assigned own language code.
- ID of the song is inputted manually, for when your archive is non-sequential.
- There is an alphabetical searchable drop-down menu for previously created
  composers and poets; these are limited to within organization.


### Managing events and projects

Events combine songs with attendance and calendar, with projects wrapping the events together in a package.

- In Attendance overview, members with active membership status appear with a checkbox for their rehearsal
  participation.
- Events can be rehearsals, performances, concerts or recording sessions.

## Support

Feel free to open issue on github.

## Licence

Apache 2.0.
