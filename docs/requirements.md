# Requirements specification

> English translation of the owner's original specification, [`requirements.ru.md`](requirements.ru.md) (kept unchanged). If the two ever differ, the original wins. Later decisions of the owner are recorded in [`architecture.md`](architecture.md).

## 1. General

**Purpose:** a web application that automates stock control and inventory counts for a small bar.

**Goal:** replace manual bookkeeping in Excel; keep track of stock levels, receipts, write-offs and the discrepancies found by inventory counts.

**Form:** a web application used in a browser on computers, tablets and smartphones.

**Scale:** one venue with several storage locations.

## 2. Functional requirements

### 2.1. Dashboard

- Number of products.
- Total value of the stock.
- Current stock levels.
- Products with low stock.
- Latest receipts and write-offs.
- Results of the latest inventory counts.

### 2.2. Product catalog

For every product the following is stored:

- Name.
- Article number (SKU).
- Category.
- Unit of measure.
- Purchase price.
- Minimum stock.
- Barcode (optional).

Product categories:

- Alcohol.
- Soft drinks.
- Food and ingredients.
- Supplies.
- Other.

Supported units: pieces, bottles, liters, milliliters, kilograms and grams.

Products can be created, edited, searched and deactivated.

### 2.3. Warehouses and storage locations

- Create and edit storage locations.
- Stock is kept separately for each location.
- The total quantity of a product over all locations can be viewed.
- Products can be transferred between locations, with the history of operations kept.

Examples: main storeroom, bar counter, fridge.

### 2.4. Receipts

- Register incoming goods.
- Several products in one document.
- Quantity and purchase price.
- Date of receipt.
- Stock increases automatically.
- History of receipts.

### 2.5. Inventory counts

The core module of the application.

- Start a count for a chosen storage location.
- The expected (book) quantities are shown automatically.
- Enter the actual counted quantities.
- Discrepancies are calculated automatically.
- The value of the discrepancies is calculated.
- Results are saved.
- The count is confirmed and completed.
- History of previous counts.

Once a count is confirmed, the counted quantities become the new book stock.

### 2.6. Write-offs

- Choose the product and the storage location.
- Quantity.
- Reason.
- Comment.
- Date of the operation.
- Stock decreases automatically.

Reasons: spoilage, expiry, breakage, staff use, other.

### 2.7. Movement journal

One history of all stock movements:

- Receipts.
- Write-offs.
- Transfers.
- Adjustments from inventory counts.

Filters by date, product, storage location and operation type.

## 3. Alcohol specifics

The system must handle partly used bottles.

Example: a 700 ml bottle with 350 ml actually left.

Conversion between units must be provided, e.g. between bottles and milliliters.

## 4. Users and permissions

Sign-in and two roles:

| Role | Permissions |
|---|---|
| Administrator | Full access to every function |
| Staff | View stock, enter counted quantities, perform the permitted operations |

## 5. Non-functional requirements

- Data stored and processed correctly.
- Protection against unauthorized access.
- The history of stock operations is kept.
- Concurrent operations cannot corrupt the stock levels.
- Database backups.
- Responsive interface.
- The system can be extended later.

## 6. Interface requirements

- Modern, minimalist design.
- Navigation sidebar.
- Tables with search, sorting and filters.
- Convenient forms for adding and editing data.
- Clear display of stock levels and discrepancies.
- The main interface language is English.
- Localization into Russian and Korean must be possible later.

## 7. Technology constraints

The technology stack is chosen at the design stage.

Main requirements:

- Separate client and server parts.
- A relational database.
- Frontend and backend can evolve independently.
- Integration with POS systems must be possible later.
- A separate mobile application must be possible on top of the existing backend API.

## 8. Out of scope for the first version (MVP)

The first version does not include:

- Integration with POS systems.
- Automatic write-off of ingredients by sales.
- Recipe cards and cocktail recipes.
- A mobile application.
- Automated ordering from suppliers.
- Several venues.
- Complex financial analytics.

**Deliverable:** a production-ready web application for stock control and inventory counts in a small bar, which can be extended later.

> Note: after the MVP the owner asked for a POS sales import with kitchen norms (items 1 and 2 of section 8, in a file-based form). See [`architecture.md`](architecture.md), section 11.
