# inventory
Inventory Management System
This is a Flask-based web application for managing inventory, invoices, purchases, returns, and sales for a retail business, specifically designed for handling apparel products like bras, panties, camisoles, and nighties. It includes PDF invoice processing, database management with SQLite, and a front-end interface for data visualization and interaction.
Why This Is Important

Efficient Inventory Tracking: Centralizes inventory data (purchases, sales, returns) to provide real-time stock insights.
Invoice Management: Extracts and stores data from PDF invoices, enabling easy tracking of orders and returns.
Return Handling: Supports marking invoices as returns with details like return type, stock addition, and loss amount.
Scalability: Modular APIs and database structure allow for easy extension to support additional features.
Data Insights: Provides summaries and counts (total bills, returns, actual sales) for business analytics.

Prerequisites

Python 3.8+
Node.js (for front-end dependencies, if applicable)
SQLite (included with Python)
Web browser (Chrome, Firefox, etc.)
Git (for cloning the repository)

Installation

Clone the Repository:
git clone <repository-url>
cd inventory-management-system


Set Up a Virtual Environment:
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate


Install Python Dependencies:
pip install flask pymupdf pandas openpyxl werkzeug


Set Up Front-End Dependencies (if using provided JavaScript):

Ensure jQuery and DataTables are included. Add to your HTML or install via npm:npm install jquery datatables.net datatables.net-dt


Include in HTML:<script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
<link rel="stylesheet" href="https://cdn.datatables.net/1.11.5/css/jquery.dataTables.min.css">
<script src="https://cdn.datatables.net/1.11.5/js/jquery.dataTables.min.js"></script>




Create Uploads Directory:
mkdir uploads



Running the Application

Initialize the Database:

The application automatically creates and populates inventory.db with default categories, types, sizes, and suppliers on first run.


Start the Flask Server:
python app.py


The server runs on http://0.0.0.0:8000 in debug mode.


Access the Application:

Open a browser and navigate to http://localhost:8000.
Use the front-end interface to interact with the inventory system.



Key Features

Inventory Management: Add, update, delete, and merge categories, types, sizes, and suppliers.
Purchases and Sales: Track stock purchases, ready-to-sale items, and sales with quantity validation.
Returns: Mark invoices as returns (customer, supplier, or damaged), with options to add to stock and record loss amounts.
Invoice Processing: Upload PDF invoices, extract metadata (e.g., invoice number, customer name), and save to database.
Summaries: View total bills, returns, actual sales, and detailed sales/return summaries via DataTables.

API Endpoints

GET /api/invoice_summary: Returns total bills, returns, actual sales, and detailed summary.
POST /api/invoices/mark_return: Marks an invoice as a return with details (return type, category, etc.).
POST /api/invoices/delete: Deletes an invoice if not marked as returned.
GET /api/: Retrieves data from categories, types, sizes, or suppliers.POST /upload: Processes uploaded PDF invoices and extracts metadata.GET /api/invoices/list: Lists saved invoices with return status and metadata.Front-End Usage
View Invoice Summary:

The fetchInvoiceSummary function populates a DataTable with invoice details and displays counts (total bills, returns, actual sales).
HTML includes a table (#summaryTable) and spans for counts (#totalBills, #totalReturns, #actualSales).


Mark Return:

Click "Mark Return" on an invoice row to open a modal.
Select return type, category, type, size, supplier, quantity, loss amount, and reason.
Submit updates the database and refreshes the table.


Delete Invoice:

Click "Delete" on an invoice row to remove it (blocked if marked as returned).
Confirmation prompt ensures accidental deletions are avoided.


Troubleshooting
Database Issues: Ensure inventory.db is writable and not corrupted. Recreate by running truncate_database endpoint.
PDF Processing Errors: Verify PyMuPDF is installed and PDFs are valid.
Modal Not Showing: Check if returnModal is appended to DOM and display: flex is applied.
API Errors: Inspect browser console for network errors and ensure Flask server is running.
AuthorShovan GhoraiSenior Software DeveloperLicenseMIT License - feel free to use and modify as needed.










