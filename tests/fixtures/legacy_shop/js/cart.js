// Cart helpers loaded on every page.
$(function () {
  fetch('api.php?action=cart_count')
    .then(function (r) { return r.json(); })
    .then(function (data) { $('#cart-count').text(data.count); });

  $('.remove-item').on('click', function (e) {
    e.preventDefault();
    var row = $(this).closest('tr');
    $.ajax({
      url: 'api.php?action=remove_from_cart',
      type: 'POST',
      data: { item_id: row.data('item') },
      dataType: 'json',
      success: function () { row.remove(); }
    });
  });

  $('#search-form input[name=q]').on('keyup', function () {
    $.getJSON('api.php?action=search&q=' + encodeURIComponent($(this).val()), function (rows) {
      // render suggestions
    });
  });
});
