import os
import jwt
from flask import Flask, jsonify, request
from pymongo import MongoClient
from datetime import datetime, timedelta
import pytz
from decouple import config
from flasgger import Swagger
import git
import bcrypt
import secrets
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import r2_score

app = Flask(__name__)
swagger = Swagger(app)

# Access environment variables
app.config['cluster_username'] = config('CLUSTER_USERNAME')
app.config['cluster_password'] = config('CLUSTER_PASSWORD')
app.config['cluster_uri'] = config('CLUSTER_URI')

# Replace 'YOUR_CONNECTION_URI' with your MongoDB Atlas connection string
app.config['MONGO_URI'] = "mongodb+srv://{}:{}@{}/?retryWrites=true&w=majority".format(app.config['cluster_username'], app.config['cluster_password'], app.config['cluster_uri'])

'mongodb+srv://mongocluster:mongocluster@mongocluster.rj9zaak.mongodb.net/?retryWrites=true&w=majority'

# Initialize PyMongo
mongo = MongoClient(app.config['MONGO_URI'])

# Access a specific database and collection
db = mongo.get_database('smart-budget-planner')

def validate_access_token(token):
    decoded_token = jwt.decode(token, options={"verify_signature": False})
        
    # Extract the expiration timestamp from the decoded token (standard claim: 'exp')
    expiration_timestamp = decoded_token['exp']
    
    # Convert the timestamp to a datetime object
    expiration_datetime = datetime.utcfromtimestamp(expiration_timestamp)
    
    # Compare with the current time (UTC)
    current_datetime = datetime.utcnow()

    
    # If the token has not expired, return False; otherwise, return True
    return expiration_datetime > current_datetime

@app.before_request
def before_request():
    if request.path == '/transactions' or request.path == '/predict':
        # Validate the access token for each request
        token = request.headers.get('Authorization').split(' ')[1]
        if not validate_access_token(token):
            return jsonify({"error": "Unauthorized"}), 401
    else:
        return  # Skip access token validation for the /login route   

@app.route('/')
def index():
    return "Smart Budget Planner API"

@app.route('/predict', methods=['POST'])
def predict_budget_status():
    """
    Predict Budget Status
    ---
    parameters:
      - name: budget
        in: formData
        type: number
        required: true
        description: The user's budget for the current month.
      - name: transactions
        in: body
        schema:
          type: array
          items:
            type: object
            properties:
              Date:
                type: string
                format: date
                example: "2023-10-05"
              Amount:
                type: number
                example: 300
        required: true
        description: The user's current month's transactions.

    responses:
      200:
        description: Budget status and difference.
        schema:
          type: object
          properties:
            budget_status:
              type: string
              description: The budget status (over budget/under budget).
            budget_difference:
              type: number
              description: The budget difference.
            model_accuracy_r_squared:
              type: number
              description: The R-squared value representing model accuracy.
    """
    # Use a regressor for forecasting
    model = RandomForestRegressor()
    # Get today's date
    today = datetime.now().date()

    # Calculate the date 3 months ago
    one_year_ago = today - timedelta(days=365)

    collection = db['transactions']
    # Get the 'from' and 'to' date parameters from the query string
    from_date = one_year_ago.strftime('%Y-%m-%d')
    to_date = today.strftime('%Y-%m-%d')

    # Convert 'from' and 'to' date strings to datetime objects and explicitly set them to UTC timezone
    from_date = datetime.strptime(from_date, '%Y-%m-%d')
    from_date = pytz.utc.localize(from_date)

    # Adjust 'to_date' to include the end of the day (23:59:59.999999)
    to_date = datetime.strptime(to_date, '%Y-%m-%d')
    to_date = pytz.utc.localize(to_date).replace(hour=23, minute=59, second=59, microsecond=999999)

    token = request.headers.get('Authorization').split(' ')[1]
    decoded_token = jwt.decode(token, options={"verify_signature": False})
    user_id = decoded_token.get('user_id')
    # Define the query to filter transactions by date range
    query = {"timestamp": {"$gte": from_date, "$lte": to_date}, "user_id": str(user_id)}

    # Use the query to retrieve transactions in the specified date range
    transactions_in_range = list(collection.find(query))
    # Convert ObjectId fields to strings
    transaction_dates = []
    transaction_amounts = []
    for transaction in transactions_in_range:
        transaction['_id'] = str(transaction['_id'])
        transaction_dates.append(transaction['timestamp'].strftime('%Y-%m-%d'))
        transaction_amounts.append(transaction['amount'])


    historical_data = pd.DataFrame({
    'Date': transaction_dates,
    'Amount': transaction_amounts
    })
    budget = request.json['budget']
    current_month_data = pd.DataFrame(request.json['transactions'])
    
    current_month_data['Date'] = pd.to_datetime(current_month_data['Date'])
    current_month_data['Month'] = current_month_data['Date'].dt.month

    # Combine historical data and current month's data
    all_data = pd.concat([historical_data, current_month_data], ignore_index=True)

    # Feature engineering to extract month
    all_data['Date'] = pd.to_datetime(all_data['Date'])
    all_data['Month'] = all_data['Date'].dt.month

    # Group by month and sum the amounts
    monthly_total = all_data.groupby('Month')['Amount'].sum().reset_index()

    # Use the monthly total for forecasting
    X_train = monthly_total['Month'].values.reshape(-1, 1)
    y_train = monthly_total['Amount']

    model.fit(X_train, y_train)

    # Predict the expected monthly total expenses for the current month
    current_month = current_month_data['Month'].iloc[0]
    expected_expenses = model.predict([[current_month]])[0]

    # Calculate the budget difference based on monthly total expenses
    budget_difference = budget - expected_expenses

    # Determine budget status and budget difference message
    if budget_difference < 0:
        budget_status = "Over Budget"
        budget_difference = abs(budget_difference)
    else:
        budget_status = "Under Budget"

    # Calculate R-squared value as a measure of model accuracy
    r_squared = r2_score(y_train, model.predict(X_train))

    response = {
        'budget_status': budget_status,
        'budget_difference': budget_difference,
        'model_accuracy_r_squared': r_squared
    }

    return jsonify(response)



@app.route('/signup', methods=['POST'])
def signup():
    """
    Register a new user.

    ---
    tags:
      - Authentication
    parameters:
      - name: name
        in: formData
        type: string
        required: true
        description: Name for the new user
      - name: username
        in: formData
        type: string
        required: true
        description: Username for the new user
      - name: password
        in: formData
        type: string
        required: true
        description: Password for the new user
    responses:
      201:
        description: User registered successfully.
      400:
        description: Username already exists.
      500:
        description: Internal Server Error.
    """
    try:
        collection = db['users']
        
        # Get username and password from request body
        name = request.json.get('name')
        username = request.json.get('username')
        password = request.json.get('password')

        if name is None or username is None or password is None:
          return jsonify({'error': 'Bad request - Missing attributes', 'status': 400}), 400

        # Check if the username already exists
        existing_user = collection.find_one({'username': username})
        if existing_user:
            return jsonify({'message': 'Username already exists', 'status': 400}), 400

        # Hash the password using bcrypt
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

        # Store the user's data in the database with the hashed password
        user_data = { 'name': name, 'username': username, 'password': hashed_password }
        collection.insert_one(user_data)

        return jsonify({'message': 'Signup successful', 'status': 201}), 201

    except Exception as e:
        return jsonify({'error': str(e), 'status': 500}), 500

@app.route('/login', methods=['POST'])
def login():
    """
    Authenticate a user.

    ---
    tags:
      - Authentication
    parameters:
      - name: username
        in: formData
        type: string
        required: true
        description: Username of the user
      - name: password
        in: formData
        type: string
        required: true
        description: Password of the user
    responses:
      200:
        description: Login successful.
      403:
        description: Invalid username or password.
      500:
        description: Internal Server Error.
    """
    try:
        collection = db['users']
        
        # Get username and password from request body
        username = request.json.get('username')
        password = request.json.get('password')
        # Find user by username
        user = collection.find_one({'username': username})
        
        if user:
            # Check if the provided password matches the stored hashed password
            if bcrypt.checkpw(password.encode('utf-8'), user['password']):
                # Set the expiration time for the JWT (24 hours from the current time)
                expiration_time = datetime.utcnow() + timedelta(hours=24)

                # Create a JWT containing the username and an "exp" (expiration) claim
                access_token = jwt.encode({'username': username, 'user_id': str(user.get('_id')), 'name': user.get('name'), 'exp': expiration_time}, 'your_secret_key', algorithm='HS256')

                # Return the access token in the response
                return jsonify({"access_token": access_token, "message": "Login successful"}), 200

        # Authentication failed
        return jsonify({'message': 'Invalid username or password', 'status': 403}), 403

    except Exception as e:
        return jsonify({'error': str(e), 'status': 500}), 500



@app.route('/transactions', methods=['GET'])
def get_transactions():
    """
    Get transactions within a date range.

    ---
    tags:
      - Transactions
    parameters:
      - name: from
        in: query
        type: string
        format: date
        required: true
        description: Start date (YYYY-MM-DD)
      - name: to
        in: query
        type: string
        format: date
        required: true
        description: End date (YYYY-MM-DD)
    responses:
      200:
        description: List of transactions within the date range.
        schema:
          type: object
          properties:
            transactions:
              type: array
              items:
                type: object
                properties:
                  _id:
                    type: string
                  amount:
                    type: number
                  description:
                    type: string
                  timestamp:
                    type: string
                  type:
                    type: string
      500:
        description: Internal Server Error.
    """
    try:
        token = request.headers.get('Authorization').split(' ')[1]
        decoded_token = jwt.decode(token, options={"verify_signature": False})
        user_id = decoded_token.get('user_id')
        collection = db['transactions']
        # Get the 'from' and 'to' date parameters from the query string
        from_date = request.args.get('from')
        to_date = request.args.get('to')

        # Convert 'from' and 'to' date strings to datetime objects and explicitly set them to UTC timezone
        from_date = datetime.strptime(from_date, '%Y-%m-%d')
        from_date = pytz.utc.localize(from_date)

        # Adjust 'to_date' to include the end of the day (23:59:59.999999)
        to_date = datetime.strptime(to_date, '%Y-%m-%d')
        to_date = pytz.utc.localize(to_date).replace(hour=23, minute=59, second=59, microsecond=999999)

        # Define the query to filter transactions by date range
        query = {"timestamp": {"$gte": from_date, "$lte": to_date}, "user_id": user_id}

        # Use the query to retrieve transactions in the specified date range
        transactions_in_range = list(collection.find(query))
        # Convert ObjectId fields to strings
        for transaction in transactions_in_range:
            transaction['_id'] = str(transaction['_id'])

        return jsonify({"transactions": transactions_in_range})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/transactions', methods=['POST'])
def create_transaction():
    """
    Create a new transaction.

    ---
    tags:
      - Transactions
    parameters:
      - name: transaction_data
        in: body
        required: true
        schema:
          type: object
          properties:
            amount:
              type: number
            description:
              type: string
            type:
              type: string
    responses:
      201:
        description: Transaction created successfully.
        schema:
          type: object
          properties:
            message:
              type: string
            transaction:
              type: object
      500:
        description: Internal Server Error.
    """
    try:
        token = request.headers.get('Authorization').split(' ')[1]
        decoded_token = jwt.decode(token, options={"verify_signature": False})
        user_id = decoded_token.get('user_id')
        collection = db['transactions']
        # Get the transaction data from the request JSON
        transaction_data = request.get_json()
        transaction_data['timestamp'] = datetime.now()
        transaction_data['user_id'] = user_id

        # Insert the new transaction into the collection
        result = collection.insert_one(transaction_data)

        # Return the newly created transaction with its generated ObjectId
        new_transaction_id = str(result.inserted_id)
        transaction_data['_id'] = new_transaction_id
        return jsonify({"message": "Transaction created successfully", "transaction": transaction_data}), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80, debug=True)
