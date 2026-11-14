<?php
session_start();
require_once 'includes/db.php';

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    header('Location: cart.php');
    exit;
}

$name = mysqli_real_escape_string($conn, $_POST['full_name']);
$email = mysqli_real_escape_string($conn, $_POST['email']);
$address = mysqli_real_escape_string($conn, $_POST['address']);
$coupon = isset($_POST['coupon']) ? $_POST['coupon'] : '';
$user_id = isset($_SESSION['user_id']) ? (int)$_SESSION['user_id'] : 0;
$sid = session_id();

mysqli_query($conn, "INSERT INTO orders (user_id, full_name, email, address, status, created_at) VALUES ($user_id, '$name', '$email', '$address', 'new', NOW())");
$order_id = mysqli_insert_id($conn);
mysqli_query($conn, "INSERT INTO order_items (order_id, product_id, quantity, unit_price) SELECT $order_id, c.product_id, c.quantity, p.price FROM cart_items c JOIN products p ON p.id = c.product_id WHERE c.session_id = '$sid'");
mysqli_query($conn, "DELETE FROM cart_items WHERE session_id = '$sid'");

header('Location: thanks.php?order=' . $order_id);
