# LEARN2EARN-LENDER (equipment/utility lending system)

##

detailed build plan in **[BUILD PLAN](BUILD_PLAN.md)**

> "Fellows" are students under the organization "Learn2Earn", Piscine candidates are prospective fellows under trials to get into the Learn2Earn program, learn2earn are the organization providers 
Fellows and piscine candidates are the borrowers

##

* per day json srorage
* equipment details
* store (what is left, what is out, what is needed,  what is faulty, what is damaged, etc)
* add equipment
* checkout equipment
* return equipment
* remove equipment
* find equipment
* find by category
* time/date logging
* get fellow lending history
* Fellow student details

## starting data(editable)

```python
resources = [
  {"id": "R001", "name": "Laptop", "category": "Electronics", "total": 10, "available": 10},
  {"id": "R002", "name": "Keyboard", "category": "Accessories", "total": 5, "available": 5},
  {"id": "R003", "name": "Headset", "category": "Accessories", "total": 3, "available": 3}
]
fellows = {"F001": "Ada", "F002": "John", "F003": "Grace"}
borrow_records = []
```

these starting data are not absolute, they are test data, i believe you can tweak them when necessary

##

fellows should be classified into groups called cohort

```text
fellow/
     |---cohort/
     |      |-------cluster-1-feb
     |      |-------cluster-2-feb
     |      |-------cluster-3-feb
     |      |-------cluster-4-feb
     |      |-------july-cohort
     |---piscine-trials/
     |      |-------trial-period
     |      |-------trial-period
     |      |-------trial-period
     |      |-------trial-period
     |      |-------trial-period
     |      |-------trial-period
```

cohort should be addable so that when a new cohort resumes after a successful piscine trial they can be added to the "fellow/cohort/" directory

##

equipments should be structured similar to this (editable)

```text
fellow/
     |---electronics/
     |         |---desktop-computer
     |         |---laptop
     |---accessories/
     |         |---keyboard
     |         |---mouse
     |         |---mouse-pad
     |         |---others
     |---utilities/
     |         |---chairs
     |         |---internet-access
     |         |---facility-access
```

##

1. Prevent issuing more than available.
2. Preserve complete transaction history.
3. Update availability based on issued and returned quantities.
4. Validate quantities, IDs, and dates.
5. Prevent over-returning.
6. very detailed data modelling
7. borrowers are registered fellows and or piscine/trial candidates
8. due dates and overdue tracking
9. csv/json export and import system
10. input validation
11. resources with fewer than 3 available units
12. resource with most units currently borrowed
13. identify all tied leader
14. No frameworks, databases, external services, or third-party packages 15. required. Use Python standard library only.
15. application should run locally

## run the application
### fomr the root directory run 
```txt
python -m lender menu (for the interactive menu)
python -m lender --help (to see documentations on all available commands and flags)
python -m lender list-resources
python -m lender list-borrowers --cohort july-cohort
python -m lender checkout R004 F001 2 --days 7
python -m lender report-store-status
python -m lender report-low-stock
python -m lender report-most-borrowed

```
### from any directory (works from any directory)
```txt
python path-to-application-folder\learn2earn-lender\lender.py menu
```

### if the store is empty
The repository ships with a populated `data/` directory, so this is only needed
if `data/` is missing or you are pointing `--data-dir` somewhere new.

```txt
python -m lender seed (start from the baseline stock)
python -m lender seed --mock-fellows 400 --mock-piscine 120 --mock-equipment 60 --mock-cohorts 5 --mock-trials 10 --mock-loans 400 (a full mock dataset)
python -m lender seed --force (discard existing data and start over)
```
Seeding twice is refused unless `--force` is passed, so it will not overwrite a store by accident.

### global flags (must come BEFORE the command)
```txt
python -m lender --data-dir ./somewhere-else list-resources (use a different store; default is ./data)
python -m lender --actor grace checkout R001 F001 2 (name recorded on every event you write; default is admin)
python -m lender --json list-resources (machine-readable output instead of tables)
python -m lender --version
```
Putting a global flag after the command is an error: `lender: error: unrecognized arguments: --json`

### exit codes
```txt
0 success
1 general error
2 validation error (bad input, bad quantity, bad date)
3 not found (unknown resource, borrower, loan or group)
4 conflict (duplicate ID, not enough stock, over-return)
5 invariant violation (stored data does not add up)
6 storage error (unreadable or unwritable data directory)
7 import conflict
```

### running the tests
```txt
python -m unittest discover -s tests (from the root directory)
```