# LEARN2EARN-LENDER (equipment/utility lending system)

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
