const express = require('express');
const cors = require('cors');
const fs = require('fs');
const path = require('path');

const app = express();
const PORT = process.env.PORT || 3201;
const DB_PATH = path.join(__dirname, 'data', 'db.json');

// Middleware
app.use(cors());
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public'))); // Serve static files for UI

// --- In-memory Data Store ---
const defaultDb = {
    customers: [],
    plans: [
        { id: 'plan_basic_monthly', name: 'Basic Monthly', base_price: 1000, price_per_user: 500 },
        { id: 'plan_pro_monthly', name: 'Pro Monthly', base_price: 2500, price_per_user: 1000 },
        { id: 'plan_enterprise_yearly', name: 'Enterprise Yearly', base_price: 250000, price_per_user: 8000 },
    ],
    subscriptions: [],
    invoices: []
};

let db = { ...defaultDb }; // Start with defaults

// Load data from file if exists, otherwise initialize
try {
    if (fs.existsSync(DB_PATH)) {
        const data = fs.readFileSync(DB_PATH, 'utf8');
        const loadedData = JSON.parse(data);
        // Merge loaded data with defaults to ensure all keys exist
        db = {
            customers: loadedData.customers || [],
            plans: loadedData.plans || defaultDb.plans, // Keep defaults if plans are missing
            subscriptions: loadedData.subscriptions || [],
            invoices: loadedData.invoices || []
        };
        console.log('Loaded and merged data from db.json');
    } else {
        fs.writeFileSync(DB_PATH, JSON.stringify(db, null, 2), 'utf8');
        console.log('Initialized db.json');
    }
} catch (err) {
    console.error("Error handling DB file:", err);
    // Initialize with defaults if file is corrupted or unreadable
    db = { ...defaultDb }; // Reset to defaults on error
    fs.writeFileSync(DB_PATH, JSON.stringify(db, null, 2), 'utf8');
    console.log('Error loading db.json, initialized with default data.');
}

// Function to persist data
const saveData = () => {
    try {
        fs.writeFileSync(DB_PATH, JSON.stringify(db, null, 2), 'utf8');
    } catch (err) {
        console.error("Error saving data to DB file:", err);
    }
};

// --- Helper Functions ---
const generateId = (prefix = 'id_') => `${prefix}${Math.random().toString(36).substr(2, 9)}`;

// --- API Endpoints ---

// --- Customers ---
app.get('/customers', (req, res) => {
    res.json(db.customers);
});

app.post('/customers', (req, res) => {
    const { name, email, address } = req.body;
    if (!name || !email) {
        return res.status(400).json({ error: 'Name and email are required' });
    }
    const newCustomer = {
        id: generateId('cust_'),
        name,
        email,
        address: address || {},
        created_at: new Date().toISOString()
    };
    db.customers.push(newCustomer);
    saveData();
    console.log(`Customer created: ${newCustomer.id} - ${newCustomer.name}`);
    res.status(201).json(newCustomer);
});

app.get('/customers/:id', (req, res) => {
    const customer = db.customers.find(c => c.id === req.params.id);
    if (customer) {
        res.json(customer);
    } else {
        res.status(404).json({ error: 'Customer not found' });
    }
});

// --- Plans ---
app.get('/plans', (req, res) => {
    res.json(db.plans);
});

// Add POST /plans if needed later

// --- Subscriptions ---
app.get('/subscriptions', (req, res) => {
    res.json(db.subscriptions);
});

app.post('/subscriptions', (req, res) => {
    const { customer_id, plan_id, user_count = 1, addons = [] } = req.body;

    // Basic Validation
    if (!customer_id || !plan_id) {
        return res.status(400).json({ error: 'customer_id and plan_id are required' });
    }
    const customer = db.customers.find(c => c.id === customer_id);
    if (!customer) {
        return res.status(404).json({ error: `Customer not found: ${customer_id}` });
    }
    const plan = db.plans.find(p => p.id === plan_id);
    if (!plan) {
        return res.status(404).json({ error: `Plan not found: ${plan_id}` });
    }

    const newSubscription = {
        id: generateId('sub_'),
        customer_id,
        plan_id,
        user_count: parseInt(user_count, 10),
        addons,
        status: 'active', // Default to active
        created_at: new Date().toISOString()
    };
    db.subscriptions.push(newSubscription);
    saveData();
    console.log(`Subscription created: ${newSubscription.id} for customer ${customer_id}`);
    // Potential next step: Generate an initial invoice here
    res.status(201).json(newSubscription);
});

app.get('/subscriptions/:id', (req, res) => {
    const subscription = db.subscriptions.find(s => s.id === req.params.id);
    if (subscription) {
        res.json(subscription);
    } else {
        res.status(404).json({ error: 'Subscription not found' });
    }
});

// --- Invoices ---
app.get('/invoices', (req, res) => {
    // Add filtering later if needed (e.g., by customer_id)
    res.json(db.invoices);
});

// Add POST /invoices if needed for manual creation or regeneration

// --- Root Endpoint ---
app.get('/', (req, res) => {
    res.sendFile(path.join(__dirname, 'public', 'index.html'));
});


// --- Server Start ---
app.listen(PORT, () => {
    console.log(`Mock Orb API listening on port ${PORT}`);
    console.log(`Access the UI at http://localhost:${PORT}`);
});

// Graceful shutdown
process.on('SIGINT', () => {
    console.log('Shutting down server...');
    saveData(); // Ensure data is saved on exit
    process.exit(0);
});
