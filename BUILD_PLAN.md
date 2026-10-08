# Learn2Earn Lender — Build Plan

## 1. Product Summary

Learn2Earn Lender is a local Python CLI application for managing equipment lending within the Learn2Earn organization. It stores resource inventory, records equipment checkout and return activity, preserves complete lending history, and produces inventory and lending reports.

The application uses only the Python standard library. It must run locally without a database engine, framework, external service, or third-party package.

## 2. Core Concepts

### People

There are two borrower groups:

1. **Fellows**
   - Students accepted into the Learn2Earn program.
   - Organized into cohorts.
   - Cohorts are addable after successful Piscine trials.

2. **Piscine candidates**
   - Prospective fellows participating in trial periods.
   - Organized into named trial periods.
   - They can borrow resources but remain distinguishable from Fellows.

### Cohort and Trial Structure

```text
fellows/
├── cohorts/
│   ├── cluster-1-feb
│   ├── cluster-2-feb
│   ├── cluster-3-feb
│   ├── cluster-4-feb
│   └── july-cohort
└── piscine-trials/
    ├── trial-period-1
    ├── trial-period-2
    ├── trial-period-3
    ├── trial-period-4
    ├── trial-period-5
    └── trial-period-6
```

Cohorts and trial periods should be treated as groups, not hard-coded values. The CLI should support creating, listing, and assigning people to these groups.

### Equipment Taxonomy

Equipment is organized by category and subcategory. Neither categories nor subcategories are hard-coded values.

The initial structure is only seed data:

```text
equipment/
├── electronics/
│   ├── desktop-computer
│   └── laptop
├── accessories/
│   ├── keyboard
│   ├── mouse
│   ├── mouse-pad
│   └── others
└── utilities/
    ├── chairs
    ├── internet-access
    └── facility-access
```

The application should support:

- Creating equipment categories.
- Listing equipment categories.
- Creating subcategories within a category.
- Listing subcategories within a category.
- Assigning equipment types or resources to a category and subcategory.
- Updating and removing taxonomy values when no active dependency prevents removal.

For example, `Electronics`, `Accessories`, and `Utilities` are editable seed categories, not fixed domain rules.

Equipment records should include enough information to support accurate inventory and condition reporting.

## 3. Startup Data

The application should be seeded with editable startup data. Existing seed records must be preserved and may be extended.

### Initial Resources

```json
[
  {
    "id": "R001",
    "name": "Laptop",
    "category": "Electronics",
    "subcategory": "laptop",
    "total": 10,
    "available": 10
  },
  {
    "id": "R002",
    "name": "Keyboard",
    "category": "Accessories",
    "subcategory": "keyboard",
    "total": 5,
    "available": 5
  },
  {
    "id": "R003",
    "name": "Headset",
    "category": "Accessories",
    "subcategory": "others",
    "total": 3,
    "available": 3
  }
]
```

### Initial Borrowers

```json
{
  "F001": {
    "name": "Ada",
    "type": "fellow",
    "cohort": "cluster-1-feb",
    "status": "active"
  },
  "F002": {
    "name": "John",
    "type": "fellow",
    "cohort": "cluster-2-feb",
    "status": "active"
  },
  "F003": {
    "name": "Grace",
    "type": "fellow",
    "cohort": "cluster-3-feb",
    "status": "active"
  }
}
```

### Mock Data Tooling

Mock data is development tooling used to test and demonstrate the system. It is not a capacity limit.

Mock generation should support creating:

- Fellows and Piscine candidates.
- Cohorts and Piscine trial periods.
- Equipment categories and subcategories.
- Equipment types and stock quantities.
- Checkout, return, and overdue transactions.

The number of generated people and equipment records must not be capped by the application. Any practical limit should come from command arguments or system resources.

Seed generation should be deterministic so tests and local demonstrations are repeatable. Mock data must be clearly separated from required startup data and must never overwrite user data unless explicitly requested.

## 4. Functional Requirements

### Inventory Management

The CLI must support:

- Add equipment.
- Remove equipment.
- Find equipment by name or ID.
- Find equipment by category.
- List equipment.
- Record faulty equipment.
- Record damaged equipment.
- Update equipment details.

### Lending

The CLI must support:

- Checkout equipment to a registered borrower.
- Return equipment from a registered borrower.
- Assign due dates.
- Track overdue loans.
- Preserve complete transaction history.
- Get lending history by borrower.

### Store Status

The store view must report:

- What is available.
- What is currently out.
- What is needed.
- What is faulty.
- What is damaged.
- What is missing or retired.

### Reports

The reporting layer should produce accurate summaries for:

- Inventory levels.
- Equipment condition.
- Active and completed loans.
- Borrower lending history.
- Cohort or Piscine trial borrowing activity.
- Resources with fewer than 3 available units.
- Resource with the most units currently borrowed.
- All tied leaders when multiple resources share the highest borrowed quantity.

### Import and Export

The CLI must support:

- JSON export and import.
- CSV export and import.
- Date/time logging for every transaction and status change.

Import behavior should validate data before replacing or merging records. The plan should distinguish between destructive full replacement and safe append/merge imports.

## 5. Data Model

### People

Fields should include:

- `id`
- `name`
- `type`: `fellow` or `piscine`
- `group_id`: cohort ID or Piscine trial ID
- `status`
- `created_at`
- `updated_at`

### Groups

Two group types should exist:

- `cohort`
- `trial`

Fields should include:

- `id`
- `name`
- `type`
- `created_at`
- `updated_at`

### Equipment Taxonomy

Two taxonomy records should exist:

- `category`
- `subcategory`

Fields should include:

- `id`
- `name`
- `parent_id`: required for subcategories, omitted for categories
- `status`
- `created_at`
- `updated_at`

Categories and subcategories must be stored as data. New values must be creatable without changing application source code.

### Equipment

Fields should include:

- `id`
- `name`
- `category`
- `subcategory`
- `total_quantity`
- `available_quantity`
- `issued_quantity`
- `condition_counts`
- `needed_quantity`
- `status`
- `created_at`
- `updated_at`

Recommended condition counts:

- `good`
- `faulty`
- `damaged`
- `missing`
- `retired`

The equation enforced by the service layer should be:

```text
total_quantity = available_quantity + issued_quantity + faulty + damaged + missing + retired
```

If `needed_quantity` is included, it should be treated as a desired procurement target, not part of the current physical inventory equation.

### Transactions

Each lending event should be an immutable record containing:

- `transaction_id`
- `resource_id`
- `borrower_id`
- `transaction_type`: `checkout` or `return`
- `quantity`
- `issued_at`
- `due_at`
- `returned_at`
- `condition_on_issue`
- `condition_on_return`
- `issued_by`
- `notes`
- `status`: `active`, `returned`, `overdue`, `lost`, or `cancelled`

For accurate reporting, returns should be linked to their original checkout rather than recorded as disconnected events.

## 6. Storage Design

The requirement calls for per-day JSON storage. A clean layout should be:

```text
data/
├── seed/
│   ├── resources.json
│   └── people.json
├── current/
│   ├── inventory.json
│   ├── people.json
│   └── groups.json
└── transactions/
    ├── 2026-01-01.json
    ├── 2026-01-02.json
    └── 2026-01-03.json
```

Recommended behavior:

- Append daily transaction records to `data/transactions/YYYY-MM-DD.json`.
- Rebuild current inventory state from immutable transactions after startup or after import.
- Keep the current-state files as projections, not as the source of truth.
- Use one JSON document per transaction file, with metadata and a record array.
- Use an index file only if lookup performance becomes necessary.

This approach preserves history while allowing inventory state to be recomputed accurately.

## 7. Application Architecture

Use a layered, standard-library-only design:

```text
learn2earn_lender/
├── __init__.py
├── __main__.py
├── cli/
│   ├── __init__.py
│   ├── app.py
│   ├── commands/
│   │   ├── inventory.py
│   │   ├── lending.py
│   │   ├── people.py
│   │   ├── reports.py
│   │   └── data.py
│   └── output.py
├── domain/
│   ├── __init__.py
│   ├── equipment.py
│   ├── people.py
│   ├── groups.py
│   ├── taxonomy.py
│   ├── transactions.py
│   └── errors.py
├── services/
│   ├── __init__.py
│   ├── inventory_service.py
│   ├── taxonomy_service.py
│   ├── lending_service.py
│   ├── people_service.py
│   ├── reporting_service.py
│   └── import_export_service.py
├── storage/
│   ├── __init__.py
│   ├── paths.py
│   ├── json_repository.py
│   ├── transaction_log.py
│   ├── projections.py
│   └── seed_data.py
└── validators/
    ├── __init__.py
    ├── ids.py
    ├── quantities.py
    ├── dates.py
    └── strings.py
```

The boundaries should remain strict:

- **CLI layer** parses input and renders output only.
- **Domain layer** defines business rules and entities.
- **Service layer** coordinates workflows and validates operations.
- **Storage layer** handles files and persistence only.
- **Reports** read from projections built from the immutable transaction log and inventory records.

## 8. CLI Surface

The command set should be explicit and testable.

### Inventory

```text
lender add-resource
lender remove-resource
lender list-resources
lender find-resource
lender find-by-category
lender mark-condition
lender update-resource
```

### People and Groups

```text
lender add-fellow
lender add-piscine
lender list-borrowers
lender find-borrower
lender add-cohort
lender add-trial
lender list-groups
```

Group management must be dynamic rather than hard-coded.

### Equipment Taxonomy

```text
lender add-category
lender list-categories
lender update-category
lender remove-category
lender add-subcategory
lender list-subcategories
lender update-subcategory
lender remove-subcategory
```

Resource creation and update commands should use these taxonomy records when assigning a resource to a category and subcategory.

### Lending

```text
lender checkout
lender return
lender history
lender overdue
```

### Reports and Data

```text
lender report-inventory
lender report-store-status
lender report-low-stock
lender report-most-borrowed
lender report-borrower-history
lender export
lender import
lender seed
```

## 9. Validation and Invariants

The domain layer must enforce:

1. IDs are non-empty and unique.
2. Quantities are integers greater than zero.
3. Equipment cannot be issued beyond available quantity.
4. Equipment cannot be over-returned.
5. Borrowers must exist and be active.
6. Due dates must not precede issue dates.
7. Return dates must not precede issue dates.
8. Removed equipment cannot be issued.
9. Equipment removal preserves historical transaction references.
10. Total quantity must always equal available plus issued plus unavailable condition counts.
11. Every transaction has a timestamp.
12. Every condition change has a timestamp and reason.

## 10. Reporting Rules

### Low Stock

Resources with fewer than 3 available units should be returned by the low-stock report.

### Most Borrowed

The most-borrowed report should calculate units currently borrowed per resource, then return all resources tied at the highest count.

### Store Status

The store status report should combine:

- Available units.
- Issued units.
- Faulty units.
- Damaged units.
- Missing units.
- Retired units.
- Needed units.
- Low-stock warnings.

### Borrower History

A borrower history report should include:

- Borrower identity and group.
- Checkouts with issue and due dates.
- Returns with return dates and condition.
- Active loans.
- Overdue loans.
- Total lifetime borrowed units.

## 11. Testing Strategy

Use only the Python standard library, including `unittest`.

Recommended test boundaries:

1. Domain tests for inventory equations and checkout/return rules.
2. Service tests for validation, due dates, and over-return prevention.
3. Storage tests for JSON round trips and transaction-log rebuilding.
4. Report tests for low stock, most borrowed, and tied leaders.
5. CLI tests for command parsing and human-readable output.
6. Import/export round-trip tests for JSON and CSV.

## 12. Build Order

### Phase 1 — Foundations

1. Create project structure and CLI entry point.
2. Implement domain models and errors.
3. Implement validators.
4. Add JSON file storage.
5. Add deterministic seed data.

### Phase 2 — Equipment Taxonomy

6. Add category management.
7. Add subcategory management.
8. Add resource assignment to taxonomy records.
9. Add taxonomy-aware search.

### Phase 3 — Inventory

10. Add resource creation.
11. Add resource updates and removal.
12. Implement search by ID, name, category, and subcategory.
13. Implement condition tracking.
14. Add store status projection.

### Phase 4 — People

15. Add groups.
16. Add Fellows.
17. Add Piscine trial candidates.
18. Add borrower lookup and listing.

### Phase 5 — Lending

20. Implement checkout.
21. Implement return.
22. Implement due dates and overdue status.
23. Implement full transaction history.
24. Implement borrower lending history.

### Phase 6 — Reporting and Data Transfer

25. Add inventory and store-status reports.
26. Add low-stock report.
27. Add most-borrowed report with tied leaders.
28. Add JSON and CSV export.
29. Add JSON and CSV import.
30. Add report export.

## 13. Clean Code Constraints

To avoid spaghetti code:

- Keep each function focused on one responsibility.
- Keep CLI parsing separate from business logic.
- Use explicit errors instead of returning ambiguous values.
- Avoid global mutable state.
- Use small repository and service interfaces.
- Use dataclasses or typed dictionaries consistently.
- Build reports from domain services, not by directly reading files throughout the CLI.
- Keep storage format details isolated from business rules.
- Prefer deterministic outputs for testing.
